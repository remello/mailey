# app/services/rabbitmq_service.py
import pika
import json
from app.config import settings
from app.models import Email as EmailModel # To avoid confusion
# from app.db import get_db_session # For standalone use or specific cases - not directly used in publish_email_message by this module
from app.services.email_service import update_email_status # To update status after publishing
from sqlalchemy.orm import Session
from datetime import datetime, timezone # Added for mock email testing
import logging


logger = logging.getLogger(__name__)

_rabbitmq_url = settings.RABBITMQ_URL
_queue_name = settings.RABBITMQ_EMAIL_PROCESSING_QUEUE

_connection: Optional[pika.BlockingConnection] = None
_channel: Optional[pika.channel.Channel] = None

def _get_rabbitmq_connection() -> pika.BlockingConnection:
    global _connection
    if _connection is None or _connection.is_closed:
        try:
            params = pika.URLParameters(_rabbitmq_url)
            _connection = pika.BlockingConnection(params)
            logger.info("Successfully connected to RabbitMQ.")
            # print("INFO: Successfully connected to RabbitMQ.")
        except pika.exceptions.AMQPConnectionError as e:
            logger.error(f"Failed to connect to RabbitMQ at {_rabbitmq_url}: {e}", exc_info=True)
            # print(f"ERROR: Failed to connect to RabbitMQ at {_rabbitmq_url}: {e}")
            _connection = None
            raise ConnectionError(f"Failed to connect to RabbitMQ: {e}")
    return _connection

def _get_rabbitmq_channel() -> pika.channel.Channel:
    global _channel, _connection # Ensure _connection is also global here
    conn = _get_rabbitmq_connection()
    # conn should not be None here due to error handling in _get_rabbitmq_connection
    # but as a defensive check if logic changes:
    if conn is None:
         logger.error("RabbitMQ connection is not available (should have been raised earlier).")
         raise ConnectionError("RabbitMQ connection is not available.")

    if _channel is None or _channel.is_closed:
        try:
            _channel = conn.channel()
            _channel.queue_declare(queue=_queue_name, durable=True)
            logger.info(f"RabbitMQ channel obtained and queue '{_queue_name}' declared.")
            # print(f"INFO: RabbitMQ channel obtained and queue '{_queue_name}' declared.")
        except (pika.exceptions.AMQPChannelError, pika.exceptions.AMQPConnectionError) as e:
            logger.error(f"Failed to open RabbitMQ channel or declare queue: {e}", exc_info=True)
            # print(f"ERROR: Failed to open RabbitMQ channel or declare queue: {e}")
            _channel = None
            if _connection and _connection.is_open: # Use the global _connection
                try:
                    _connection.close()
                except Exception as close_exc:
                    logger.warning(f"Exception while closing RabbitMQ connection after channel error: {close_exc}", exc_info=True)
            _connection = None
            raise ConnectionError(f"Failed to open RabbitMQ channel or declare queue: {e}")
    return _channel

def publish_email_message(email: EmailModel, db: Session) -> bool:
    """
    Publishes a message to RabbitMQ for a processed email and updates its status.
    Returns True if successful, False otherwise.
    """
    # Ensure mailbox relationship is loaded if needed, or handle potential None
    mailbox_email_address = None
    if email.mailbox: # Check if relationship is loaded
        mailbox_email_address = email.mailbox.email_address
    elif hasattr(email, '_sa_instance_state'): # Check if it's a SQLAlchemy instance
        # Attempt to refresh if mailbox relationship is missing and it's a valid instance
        # This might be too aggressive or cause issues depending on session state.
        # For now, let's assume if email.mailbox is None, we proceed with None.
        # Consider logging a warning if mailbox relationship is expected but not loaded.
        logger.warning(f"Mailbox relationship not loaded for Email ID {email.id} during RabbitMQ publish.")
        pass


    message_body = {
        "db_email_id": email.id,
        "mailbox_email_address": mailbox_email_address,
        "sender": email.sender_address,
        "recipient": email.recipient_address,
        "subject": email.subject,
        "received_at_header": email.received_at_header.isoformat() if email.received_at_header else None,
        "apt_from_recipient_address": email.apt_from_recipient_address,
        "has_html_body": bool(email.body_html),
        "has_text_body": bool(email.body_text),
    }

    try:
        channel = _get_rabbitmq_channel()
        # channel should not be None here due to error handling in _get_rabbitmq_channel

        channel.basic_publish(
            exchange='',
            routing_key=_queue_name,
            body=json.dumps(message_body),
            properties=pika.BasicProperties(
                delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE
            )
        )
        logger.info(f"Email ID {email.id} published to RabbitMQ queue '{_queue_name}'.")
        # print(f"INFO: Email ID {email.id} published to RabbitMQ queue '{_queue_name}'.")

        status_updated = update_email_status(db, email.id, 'queued_for_deepseek')
        if not status_updated:
            logger.warning(f"Message for email ID {email.id} published, but DB status update failed.")
            # print(f"WARNING: Message for email ID {email.id} published, but DB status update failed.")
            return False

        return True

    except (pika.exceptions.AMQPConnectionError, pika.exceptions.AMQPChannelError) as e:
        logger.error(f"RabbitMQ connection/channel error publishing email ID {email.id}: {e}", exc_info=True)
        # print(f"ERROR: RabbitMQ connection/channel error publishing email ID {email.id}: {e}")
        global _connection, _channel # Declare them global to modify
        if _channel and _channel.is_open:
            try: _channel.close()
            except Exception: pass # nosemgrep
        if _connection and _connection.is_open:
            try: _connection.close()
            except Exception: pass # nosemgrep
        _channel = None
        _connection = None
        return False
    except Exception as e:
        logger.error(f"Unexpected error publishing email ID {email.id}: {e}", exc_info=True)
        # print(f"ERROR: Unexpected error publishing email ID {email.id}: {e}")
        return False

def close_rabbitmq_connection():
    """Closes the RabbitMQ connection if it's open."""
    global _connection, _channel # Declare them global to modify
    try:
        if _channel and _channel.is_open:
            _channel.close()
            logger.info("RabbitMQ channel closed.")
            # print("INFO: RabbitMQ channel closed.")
    except Exception as e:
        logger.warning(f"Error closing RabbitMQ channel: {e}", exc_info=True)
        # print(f"WARNING: Error closing RabbitMQ channel: {e}")
        pass # nosemgrep
    finally:
        _channel = None

    try:
        if _connection and _connection.is_open:
            _connection.close()
            logger.info("RabbitMQ connection closed.")
            # print("INFO: RabbitMQ connection closed.")
    except Exception as e:
        logger.warning(f"Error closing RabbitMQ connection: {e}", exc_info=True)
        # print(f"WARNING: Error closing RabbitMQ connection: {e}")
        pass # nosemgrep
    finally:
        _connection = None

# Example Usage (for testing this module directly):
# if __name__ == '__main__':
#     logging.basicConfig(level=logging.INFO) # Basic logging for test
#     logger.info(f"RabbitMQ URL: {settings.RABBITMQ_URL}")
#     logger.info(f"Queue Name: {_queue_name}")

#     class MockMailbox:
#         email_address = "test_mailbox@example.com"

#     # A simplified mock, not inheriting from EmailModel to avoid SQLAlchemy's machinery in test
#     class MockEmailForPublishTest:
#         id = 12345
#         sender_address = "sender@example.com"
#         recipient_address = "recipient@example.com"
#         subject = "Test Email Subject from rabbitmq_service test"
#         received_at_header = datetime.now(timezone.utc)
#         apt_from_recipient_address = "apt123"
#         body_html = "<p>Hello World HTML</p>"
#         body_text = "Hello World Text"
#         mailbox = MockMailbox() # Direct assignment of mock mailbox


#     test_email_obj = MockEmailForPublishTest()

#     # Mocking the DB session and update_email_status for the test
#     class MockDBSession:
#         def commit(self): logger.info("MockDBSession: commit() called")
#         def refresh(self, obj): logger.info(f"MockDBSession: refresh({obj}) called")

#     mock_db_session = MockDBSession()

#     original_update_email_status = update_email_status # Keep a reference if needed elsewhere

#     # Redefine update_email_status in the local scope of this test block
#     def mock_update_email_status_for_test(db_session, email_id, new_status):
#         logger.info(f"MOCK: update_email_status called for email ID {email_id} to {new_status} with session {type(db_session)}")
#         if email_id == test_email_obj.id and new_status == 'queued_for_deepseek':
#             return True
#         return False

#     # Temporarily replace the service's update_email_status with our mock
#     # This is a bit hacky for direct script execution; proper mocking libraries (unittest.mock) are better for actual tests.
#     # For this __main__ block, we can shadow the import if we are careful.
#     # However, publish_email_message uses `from app.services.email_service import update_email_status`
#     # So, we need to ensure that `email_service.update_email_status` is what gets mocked,
#     # or pass the mock function into publish_email_message if it were designed to accept it.

#     # Given the current structure, the easiest way to test publish_email_message
#     # without complex mocking setup is to test its parts or assume update_email_status works
#     # and focus on the RabbitMQ interaction.

#     # For this example, we'll just call the direct RabbitMQ interaction part.
#     print("Attempting a direct publish test (bypassing full publish_email_message function)...")
#     try:
#         _get_rabbitmq_connection() # Establish connection
#         ch = _get_rabbitmq_channel() # Establish channel & queue
#         if ch:
#             print(f"Connection and channel to RabbitMQ for queue '{_queue_name}' seem OK.")
#             message_body_test = { "db_email_id": 9999, "subject": "Direct Channel Test Message" }
#             ch.basic_publish(
#                 exchange='', routing_key=_queue_name, body=json.dumps(message_body_test),
#                 properties=pika.BasicProperties(delivery_mode=pika.spec.PERSISTENT_DELIVERY_MODE)
#             )
#             print(f"A test message directly published to '{_queue_name}'. Check RabbitMQ management.")
#         else:
#             print("Could not get RabbitMQ channel for direct test.")
#     except ConnectionError as e:
#         print(f"Direct Test Error: {e}")
#     except Exception as e:
#         print(f"Unexpected Direct Test Error: {e}", exc_info=True)
#     finally:
#         close_rabbitmq_connection()
#         print("Test: RabbitMQ connection closed.")

#     # To test publish_email_message fully, you'd do something like:
#     # print("\nAttempting to use publish_email_message with mocks...")
#     # # Need to ensure app.services.email_service.update_email_status is the mock.
#     # # This is hard to do reliably by just redefining here if it's already imported by rabbitmq_service.
#     # # A proper test suite with unittest.mock.patch would handle this.
#     # # success = publish_email_message(test_email_obj, mock_db_session) # This would call the real update_email_status
#     # # print(f"Result of publish_email_message with (semi-mocked) setup: {success}")
#     # # close_rabbitmq_connection() # Ensure connection is closed after this test too.

from typing import Optional # Added for _connection and _channel type hints
