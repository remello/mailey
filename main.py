import logging
import signal
import time
from sqlalchemy.orm import Session
from app.config import settings
from app.db import SessionLocal, get_db_session # Assuming get_db_session yields
from app.models import Mailbox # If needed for type hinting or direct use
from app.services import email_service, rabbitmq_service

# Basic Logging Configuration (will be enhanced in a later step)
logging.basicConfig(level=settings.LOG_LEVEL.upper(),
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

KEEP_RUNNING = True

def handle_signal(signum, frame):
    global KEEP_RUNNING
    logger.info(f"Signal {signum} received. Shutting down gracefully...")
    KEEP_RUNNING = False

def main_loop():
    global KEEP_RUNNING
    logger.info("Email Ingestor Service starting...")
    logger.info(f"Database URL: {settings.DATABASE_URL}")
    logger.info(f"RabbitMQ URL: {settings.RABBITMQ_URL}")
    logger.info(f"Check interval: {settings.CHECK_INTERVAL_MINUTES} minutes")
    logger.info(f"Encryption key loaded (first 5 chars): {settings.ENCRYPTION_KEY[:5]}...")

    MAX_DB_RETRIES = 3
    RETRY_DELAYS = [10, 20, 30] # Seconds

    while KEEP_RUNNING:
        db: Session = next(get_db_session()) # Acquire a new session for this cycle
        if not db: # Should not happen if get_db_session raises on failure
            logger.critical("Failed to acquire DB session. Sleeping for 60s.")
            for _ in range(60):
                if not KEEP_RUNNING: break
                time.sleep(1)
            continue

        active_mailboxes = []
        db_connection_ok = False
        for attempt in range(MAX_DB_RETRIES):
            try:
                logger.info(f"Fetching active mailboxes (attempt {attempt + 1}/{MAX_DB_RETRIES})...")
                active_mailboxes = email_service.get_active_mailboxes(db)
                logger.info(f"Found {len(active_mailboxes)} active mailboxes.")
                db_connection_ok = True
                break # Success
            except Exception as e:
                logger.error(f"Error fetching active mailboxes (attempt {attempt + 1}/{MAX_DB_RETRIES}): {e}", exc_info=True)
                if attempt < MAX_DB_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    logger.info(f"Waiting {delay} seconds before next retry...")
                    # Add KEEP_RUNNING check during sleep
                    for _ in range(delay):
                        if not KEEP_RUNNING: break
                        time.sleep(1)
                    if not KEEP_RUNNING: break # Exit retry loop if shutdown
                else:
                    logger.critical("All attempts to fetch mailboxes from DB failed.")

        if not KEEP_RUNNING: # Check after retry loop if shutdown was triggered
            if db: db.close()
            break # Exit main_loop

        if not db_connection_ok:
            logger.error("Failed to connect to DB after retries. Sleeping for 5 minutes.")
            if db: db.close()
            # Sleep for 5 minutes, checking KEEP_RUNNING
            for _ in range(5 * 60):
                if not KEEP_RUNNING: break
                time.sleep(1)
            continue # Restart main loop cycle

        if not active_mailboxes:
            logger.info("No active mailboxes found. Will check again later.")
        else:
            for mailbox in active_mailboxes:
                if not KEEP_RUNNING:
                    logger.info("Shutdown signal received during mailbox processing. Breaking loop.")
                    break

                logger.info(f"Processing mailbox: {mailbox.email_address} (ID: {mailbox.id})")
                try:
                    # process_mailbox_emails returns (successfully_saved_emails, errored_emails_data)
                    saved_emails, errored_data = email_service.process_mailbox_emails(db, mailbox)

                    logger.info(f"Mailbox {mailbox.email_address}: {len(saved_emails)} emails saved, {len(errored_data)} emails had errors during fetch/save.")

                    for email_obj in saved_emails:
                        if not KEEP_RUNNING:
                            logger.info("Shutdown signal received during RabbitMQ publishing. Breaking loop.")
                            break

                        # Emails with status 'spam_quarantined' or 'error_ingestion' should not be queued
                        if email_obj.processing_status == 'new':
                            logger.info(f"Publishing email ID {email_obj.id} (Subject: {email_obj.subject}) to RabbitMQ...")
                            try:
                                success = rabbitmq_service.publish_email_message(email_obj, db)
                                if success:
                                    logger.info(f"Email ID {email_obj.id} successfully published and status updated to 'queued_for_deepseek'.")
                                else:
                                    logger.error(f"Failed to publish email ID {email_obj.id} to RabbitMQ or update its status.")
                                    # Decide on retry strategy or if email_service should handle this
                            except ConnectionError as e:
                                logger.error(f"RabbitMQ ConnectionError for email ID {email_obj.id}: {e}. Service will attempt to reconnect later.")
                                # The rabbitmq_service has some internal retry/reconnect logic.
                                # If it fails consistently, the service might need a broader retry or alert.
                            except Exception as e:
                                logger.error(f"Unexpected error publishing email ID {email_obj.id}: {e}", exc_info=True)
                        elif email_obj.processing_status == 'spam_quarantined':
                             logger.info(f"Email ID {email_obj.id} from {email_obj.sender_address} was quarantined. Not publishing to RabbitMQ.")
                        # No action needed for 'error_ingestion' status here regarding RabbitMQ

                except Exception as e:
                    logger.error(f"Unhandled error processing mailbox {mailbox.email_address}: {e}", exc_info=True)
                    # This could be a DB error during commit within process_mailbox_emails or other unexpected issue.
                    # The session might be in an inconsistent state. Rollback is handled by get_db_session's finally block.

        if db: # Ensure session is closed after processing all mailboxes in this cycle
            db.close()

        if KEEP_RUNNING:
            logger.info(f"Waiting for {settings.CHECK_INTERVAL_MINUTES} minutes before next check...")
            for _ in range(settings.CHECK_INTERVAL_MINUTES * 60): # Check KEEP_RUNNING every second
                if not KEEP_RUNNING:
                    break
                time.sleep(1)

    logger.info("Email Ingestor Service shutting down.")
    rabbitmq_service.close_rabbitmq_connection() # Close RabbitMQ connection gracefully
    logger.info("RabbitMQ connection closed.")
    logger.info("Service stopped.")

if __name__ == "__main__":
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    main_loop()
