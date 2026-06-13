# app/services/imap_service.py
import email
import hashlib
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from typing import List, Dict, Optional, Any, Tuple
from imapclient import IMAPClient
from app.models import Mailbox as MailboxModel # To avoid confusion with mailbox objects
from app.services.encryption_service import decrypt_password
import logging
# logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

def _decode_header_value(header_value: Any) -> Optional[str]: # Changed type hint for header_value
    if header_value is None:
        return None
    if isinstance(header_value, bytes): # Handle bytes directly
        try:
            # Try common encodings or let make_header handle it
            return str(make_header(decode_header(header_value)))
        except Exception:
            try:
                return header_value.decode('utf-8', errors='replace')
            except UnicodeDecodeError:
                return header_value.decode('latin-1', errors='replace')


    if not isinstance(header_value, str): # If not str or bytes, convert to str
        header_value = str(header_value)

    try:
        # make_header expects list of (bytes, charset) tuples from decode_header
        # If it's already a string, it might be already decoded or simple ASCII
        if isinstance(header_value, str) and all(ord(c) < 128 for c in header_value): # Simple ASCII
             return header_value

        decoded_parts = decode_header(header_value)
        return str(make_header(decoded_parts))
    except Exception: # Broad exception for parsing issues
        logger.warning(f"Could not decode header value: {header_value}", exc_info=True)
        # Fallback to returning the raw value if it's already a string, or a representation
        if isinstance(header_value, str):
            return header_value
        return repr(header_value)


def extract_apt_from_recipient(recipient_address: Optional[str]) -> Optional[str]:
    """Extracts apt***** from recipient email address like company+apt12345@example.com."""
    if not recipient_address:
        return None
    # Regex to find 'apt' followed by digits in the local part of the email
    # e.g., company+apt12345@example.com -> apt12345
    # e.g., apt12345@example.com -> apt12345
    # Ensure we are looking at the local part only (before @)
    local_part = recipient_address.split('@')[0]
    match = re.search(r'(apt\d+)', local_part, re.IGNORECASE)
    if match:
        return match.group(1).lower() # Standardize to lowercase
    return None

def calculate_body_hash(text_body: Optional[str]) -> Optional[str]:
    """Calculates SHA256 hash of the text body."""
    if text_body is None:
        return None
    return hashlib.sha256(text_body.encode('utf-8')).hexdigest()

def fetch_emails_from_mailbox(mailbox_config: MailboxModel) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """
    Connects to a mailbox, fetches new emails, and processes them.
    Returns a list of dictionaries, where each dictionary contains parsed email data,
    and an updated last_checked_uid_map.
    """
    processed_emails: List[Dict[str, Any]] = []
    decrypted_password_str = decrypt_password(mailbox_config.imap_password_encrypted)

    if not decrypted_password_str:
        logger.error(f"IMAP password for {mailbox_config.email_address} is missing or decryption failed.")
        # print(f"IMAP password for {mailbox_config.email_address} is missing or decryption failed.")
        raise ValueError(f"IMAP password for {mailbox_config.email_address} is missing or decryption failed.")

    # Initialize new_last_uid_map with existing values to preserve UIDs for folders not processed or empty
    new_last_uid_map = (mailbox_config.last_checked_uid_map or {}).copy()


    try:
        with IMAPClient(host=mailbox_config.imap_host, port=mailbox_config.imap_port, ssl=True) as client:
            client.login(mailbox_config.imap_login, decrypted_password_str)
            logger.info(f"Successfully logged into {mailbox_config.email_address}")

            for folder_name in mailbox_config.monitored_folders:
                current_folder_highest_uid = new_last_uid_map.get(folder_name, 0)
                try:
                    client.select_folder(folder_name, readonly=True)
                    logger.info(f"Selected folder: {folder_name} for {mailbox_config.email_address}")

                    last_uid_processed_in_db = mailbox_config.last_checked_uid_map.get(folder_name, 0) if mailbox_config.last_checked_uid_map else 0

                    # Search for messages with UID greater than the last processed UID
                    search_criteria = [f'UID {last_uid_processed_in_db + 1}:*']
                    message_uids_on_server = client.search(search_criteria)

                    if not message_uids_on_server:
                        logger.info(f"No new messages in {folder_name} for {mailbox_config.email_address} since UID {last_uid_processed_in_db}")
                        continue

                    logger.info(f"Found {len(message_uids_on_server)} new messages in {folder_name} for {mailbox_config.email_address}")

                    for uid, message_data in client.fetch(message_uids_on_server, ['RFC822', 'INTERNALDATE']).items():
                        email_bytes = message_data[b'RFC822']
                        msg = email.message_from_bytes(email_bytes)

                        raw_headers = {k: _decode_header_value(v) for k, v in msg.items()}
                        subject = _decode_header_value(msg.get('Subject'))
                        sender = _decode_header_value(msg.get('From'))
                        recipient_header = _decode_header_value(msg.get('To'))
                        cc_header = _decode_header_value(msg.get('Cc')) # Also check Cc for apt extraction

                        actual_recipient_for_apt = mailbox_config.email_address # Default
                        # Check To then Cc for an address containing "apt" that might be the target
                        if recipient_header:
                            for r_addr in recipient_header.split(','):
                                if extract_apt_from_recipient(r_addr.strip()):
                                    actual_recipient_for_apt = r_addr.strip()
                                    break
                        if actual_recipient_for_apt == mailbox_config.email_address and cc_header: # if not found in To, check Cc
                             for c_addr in cc_header.split(','):
                                if extract_apt_from_recipient(c_addr.strip()):
                                    actual_recipient_for_apt = c_addr.strip()
                                    break

                        message_id_header = msg.get('Message-ID')

                        date_header_str = msg.get('Date')
                        received_at_header_dt = None
                        if date_header_str:
                            try:
                                received_at_header_dt = email.utils.parsedate_to_datetime(date_header_str)
                            except Exception:
                                pass

                        if not received_at_header_dt and message_data.get(b'INTERNALDATE'):
                            try:
                                internal_date = message_data[b'INTERNALDATE']
                                if isinstance(internal_date, datetime):
                                    received_at_header_dt = internal_date
                            except Exception:
                                pass

                        if received_at_header_dt and received_at_header_dt.tzinfo is None:
                            logger.warning(f"Date {received_at_header_dt} for email UID {uid} in folder {folder_name} for {mailbox_config.email_address} is naive. Assuming UTC.")
                            received_at_header_dt = received_at_header_dt.replace(tzinfo=timezone.utc)
                        elif received_at_header_dt: # Ensure it's UTC if it has timezone
                            received_at_header_dt = received_at_header_dt.astimezone(timezone.utc)


                        body_text = None
                        body_html = None

                        if msg.is_multipart():
                            for part in msg.walk():
                                content_type = part.get_content_type()
                                content_disposition = str(part.get('Content-Disposition'))

                                if "attachment" not in content_disposition.lower():
                                    charset = part.get_content_charset() or 'utf-8'
                                    if content_type == "text/plain" and body_text is None:
                                        try:
                                            body_text = part.get_payload(decode=True).decode(charset, errors='replace')
                                        except Exception: body_text = "Error decoding text part."
                                    elif content_type == "text/html" and body_html is None:
                                        try:
                                            body_html = part.get_payload(decode=True).decode(charset, errors='replace')
                                        except Exception: body_html = "Error decoding HTML part."
                        else:
                            content_type = msg.get_content_type()
                            payload = msg.get_payload(decode=True)
                            charset = msg.get_content_charset() or 'utf-8'
                            try:
                                decoded_payload = payload.decode(charset, errors='replace')
                                if content_type == "text/plain": body_text = decoded_payload
                                elif content_type == "text/html": body_html = decoded_payload
                                else: body_text = decoded_payload
                            except Exception: body_text = "Error decoding body."

                        # Fallback: if only HTML is present, use it as text_body (or implement html-to-text)
                        if body_text is None and body_html is not None:
                            logger.info(f"Email UID {uid} in folder {folder_name} for {mailbox_config.email_address} has HTML body but no plain text. Consider HTML-to-text conversion.")
                            # For now, we are not converting HTML to text.
                            # If requirements change, a library like html2text could be used here.
                            pass # body_text remains None if no plain text part found


                        email_data = {
                            "message_uid": str(uid),
                            "folder_name": folder_name,
                            "message_id_header": message_id_header,
                            "sender_address": sender,
                            "recipient_address": mailbox_config.email_address,
                            "subject": subject,
                            "body_html": body_html,
                            "body_text": body_text,
                            "received_at_header": received_at_header_dt,
                            "raw_headers": raw_headers,
                            "apt_from_recipient_address": extract_apt_from_recipient(actual_recipient_for_apt),
                            "hash_body_text": calculate_body_hash(body_text),
                        }
                        processed_emails.append(email_data)
                        current_folder_highest_uid = max(current_folder_highest_uid, int(uid))

                    if message_uids_on_server: # Update map only if messages were processed
                         new_last_uid_map[folder_name] = current_folder_highest_uid


                except IMAPClient.Error as e:
                    logger.error(f"IMAP Error for {mailbox_config.email_address}, folder {folder_name}: {e}", exc_info=True)
                    continue
                except Exception as e:
                    logger.error(f"Generic error processing folder {folder_name} for {mailbox_config.email_address}: {e}", exc_info=True)
                    continue

            return processed_emails, new_last_uid_map

    except IMAPClient.LoginError as e:
        logger.error(f"IMAP Login failed for {mailbox_config.email_address}: {e}", exc_info=True)
        raise ConnectionError(f"IMAP Login failed for {mailbox_config.email_address}: {e}")
    except ConnectionRefusedError as e: # More specific than generic socket error
        logger.error(f"IMAP connection refused for {mailbox_config.imap_host}: {e}", exc_info=True)
        raise ConnectionError(f"IMAP connection refused for {mailbox_config.imap_host}: {e}")
    except (OSError, TimeoutError) as e: # Catch other potential network errors
        logger.error(f"IMAP network error for {mailbox_config.imap_host}: {e}", exc_info=True)
        raise ConnectionError(f"IMAP network error for {mailbox_config.imap_host}: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred with IMAP operations for {mailbox_config.email_address}: {e}", exc_info=True)
        raise RuntimeError(f"An unexpected error occurred with IMAP for {mailbox_config.email_address}: {e}")

# Placeholder for MailboxModel if you want to test this file directly
# class MailboxModel:
#     def __init__(self, id, email_address, imap_host, imap_port, imap_login, imap_password_encrypted, monitored_folders, last_checked_uid_map=None):
#         self.id = id
#         self.email_address = email_address
#         self.imap_host = imap_host
#         self.imap_port = imap_port
#         self.imap_login = imap_login
#         self.imap_password_encrypted = imap_password_encrypted
#         self.monitored_folders = monitored_folders
#         self.last_checked_uid_map = last_checked_uid_map if last_checked_uid_map else {}

# if __name__ == '__main__':
#     # This is for testing; requires a .env file with ENCRYPTION_KEY and test IMAP details
#     # Ensure settings.ENCRYPTION_KEY is set in .env (generate with Fernet.generate_key().decode())
#     # logging.basicConfig(level=logging.INFO) # Basic logging for test
#     # logger.info(f"Using key: {settings.ENCRYPTION_KEY[:5]}... (ensure it's set in .env)")

#     # Example: Encrypt a password first
#     # test_pw = "your_actual_imap_password"
#     # encrypted_test_pw = encrypt_password(test_pw)
#     # logger.info(f"Store this encrypted password for your test_mailbox: {encrypted_test_pw}")

#     test_mailbox = MailboxModel(
#         id=1, # Example ID
#         email_address=os.getenv("TEST_IMAP_EMAIL", "your_test_email@example.com"),
#         imap_host=os.getenv("TEST_IMAP_HOST", "imap.example.com"),
#         imap_port=int(os.getenv("TEST_IMAP_PORT", "993")),
#         imap_login=os.getenv("TEST_IMAP_LOGIN", "your_test_email@example.com"),
#         imap_password_encrypted=os.getenv("TEST_IMAP_ENCRYPTED_PASSWORD", "gAAAAAB..."), # USE THE OUTPUT FROM encrypt_password()
#         monitored_folders=["INBOX", "TestFolder"], # Add folders to test
#         last_checked_uid_map={"INBOX": 0, "TestFolder": 0} # Start from beginning or specific UIDs
#     )

#     if "your_test_email" in test_mailbox.email_address or "gAAAAAB" not in test_mailbox.imap_password_encrypted :
#         logger.warning("Test IMAP credentials seem to be placeholders. Please set up environment variables for testing.")
#         logger.warning("TEST_IMAP_EMAIL, TEST_IMAP_HOST, TEST_IMAP_PORT, TEST_IMAP_LOGIN, TEST_IMAP_ENCRYPTED_PASSWORD")
#     else:
#         try:
#             logger.info(f"Attempting to connect to {test_mailbox.imap_host} for {test_mailbox.email_address}...")
#             retrieved_emails, updated_uid_map = fetch_emails_from_mailbox(test_mailbox)

#             if retrieved_emails:
#                 logger.info(f"Successfully fetched {len(retrieved_emails)} emails.")
#                 for mail_data in retrieved_emails:
#                     logger.info(f"  Subject: {mail_data.get('subject')}")
#                     logger.info(f"  UID: {mail_data.get('message_uid')} in Folder: {mail_data.get('folder_name')}")
#                     logger.info(f"  Sender: {mail_data.get('sender_address')}")
#                     logger.info(f"  Recipient for APT: {mail_data.get('apt_from_recipient_address')}")
#                     logger.info(f"  Hash: {mail_data.get('hash_body_text')}")
#                     logger.info(f"  Received: {mail_data.get('received_at_header')}")
#                     # logger.debug(f"  Body Text: {mail_data.get('body_text')[:100] if mail_data.get('body_text') else 'N/A'}...")
#                 logger.info(f"Updated UID map for mailbox {test_mailbox.id}: {updated_uid_map}")
#             else:
#                 logger.info("No new emails found, or an error occurred that was handled within fetch_emails_from_mailbox.")
#             logger.info(f"Final UID map to be stored for mailbox {test_mailbox.id}: {updated_uid_map}")

#         except ValueError as ve:
#             logger.error(f"Configuration or Decryption Error: {ve}", exc_info=True)
#         except ConnectionError as ce:
#             logger.error(f"Connection Error: {ce}", exc_info=True)
#         except RuntimeError as re_service: # Renamed to avoid conflict with 're' module
#             logger.error(f"Runtime Error from service: {re_service}", exc_info=True)
#         except Exception as e_generic: # Renamed to avoid conflict
#             logger.error(f"An unexpected error occurred during testing: {e_generic}", exc_info=True)
