# app/services/email_service.py
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
import logging # Setup later
from app.models import Mailbox, Email, BlockedSender
from app.services import imap_service
from app.db import SessionLocal # For standalone execution or specific cases

logger = logging.getLogger(__name__)

def get_active_mailboxes(db: Session) -> List[Mailbox]:
    """Fetches all mailboxes where is_active = TRUE."""
    return db.query(Mailbox).filter(Mailbox.is_active == True).all()

def update_mailbox_last_checked_uids(db: Session, mailbox_id: int, new_uid_map: Dict[str, int]) -> None:
    """Updates the last_checked_uid_map for a mailbox."""
    mailbox = db.query(Mailbox).filter(Mailbox.id == mailbox_id).first()
    if mailbox:
        # Ensure that the existing JSONB is updated, not replaced, if partial updates are intended
        # For this case, last_checked_uid_map is a full replacement from the latest fetch.
        mailbox.last_checked_uid_map = new_uid_map
        db.commit()
        logger.info(f"Updated last_checked_uid_map for mailbox ID {mailbox_id}: {new_uid_map}")
    else:
        logger.warning(f"Mailbox ID {mailbox_id} not found for UID map update.")
        # Consider raising an error if this is unexpected
        pass

def is_sender_permanently_blocked(db: Session, sender_address: Optional[str]) -> bool:
    """Checks if a sender is in blocked_senders and is_permanently_blocked = TRUE."""
    if not sender_address:
        return False
    # Normalize sender_address for lookup if needed (e.g., lowercase)
    # Assuming sender_address in DB is stored in a consistent format.
    blocked_sender = db.query(BlockedSender).filter(
        BlockedSender.sender_address == sender_address, # Consider .lower() if case-insensitivity is needed and not handled by DB collation
        BlockedSender.is_permanently_blocked == True
    ).first()
    return blocked_sender is not None

def get_email_by_uid_folder_mailbox(db: Session, message_uid: str, folder_name: str, mailbox_id: int) -> Optional[Email]:
    """Checks for duplicate emails based on message_uid, folder_name, and mailbox_id."""
    return db.query(Email).filter(
        Email.message_uid == str(message_uid), # Ensure UID is compared as string
        Email.folder_name == folder_name,
        Email.mailbox_id == mailbox_id
    ).first()

def save_email_to_db(db: Session, email_data: Dict[str, Any], mailbox_id: int,
                     processing_status: str = 'new', error_details: Optional[str] = None) -> Email:
    """Saves a single email to the database and returns the Email object."""

    # Critical: Email.received_at_header is NOT NULL in DB.
    # If email_data["received_at_header"] is None here, this INSERT will fail
    # unless the model is changed or a default is provided for error_ingestion status.
    # The logic in process_mailbox_emails tries to catch this specific case before calling this.

    # Defensive check for received_at_header if status is not error_ingestion
    if processing_status != 'error_ingestion' and email_data.get("received_at_header") is None:
        logger.error(f"Attempted to save email (UID: {email_data.get('message_uid')}) with 'new' status but missing received_at_header.")
        # This situation should ideally be caught by the caller (process_mailbox_emails)
        # and status set to 'error_ingestion' explicitly.
        # Raising an error here to make it clear.
        raise ValueError(f"received_at_header cannot be None for processing_status '{processing_status}'. UID: {email_data.get('message_uid')}")

    new_email = Email(
        mailbox_id=mailbox_id,
        message_uid=str(email_data["message_uid"]),
        folder_name=email_data["folder_name"],
        message_id_header=email_data.get("message_id_header"),
        sender_address=email_data.get("sender_address"), # Make sure this is handled if None
        recipient_address=email_data["recipient_address"],
        subject=email_data.get("subject"),
        body_html=email_data.get("body_html"),
        body_text=email_data.get("body_text"),
        received_at_header=email_data.get("received_at_header"), # This is the critical field
        raw_headers=email_data.get("raw_headers"),
        apt_from_recipient_address=email_data.get("apt_from_recipient_address"),
        hash_body_text=email_data.get("hash_body_text"),
        processing_status=processing_status,
        error_details=error_details
    )
    db.add(new_email)
    db.commit()
    db.refresh(new_email)
    logger.info(f"Saved email ID {new_email.id} (UID: {new_email.message_uid}) from mailbox {mailbox_id} with status {processing_status}")
    return new_email

def update_email_status(db: Session, email_id: int, new_status: str, error_details: Optional[str] = None) -> bool:
    """Updates the processing_status and optionally error_details of an email."""
    email = db.query(Email).filter(Email.id == email_id).first()
    if email:
        email.processing_status = new_status
        if error_details: # Only update if error_details is provided
            email.error_details = error_details
        elif new_status != 'error_ingestion': # Clear error_details if status is not error
             email.error_details = None
        db.commit()
        logger.info(f"Updated status of email ID {email_id} to {new_status}")
        return True
    logger.warning(f"Email ID {email_id} not found for status update.")
    return False

def process_mailbox_emails(db: Session, mailbox: Mailbox) -> Tuple[List[Email], List[Dict[str, Any]]]:
    """
    Processes a single mailbox: fetches emails via IMAP, checks for duplicates/blocked senders,
    saves new emails, and updates the mailbox's last_checked_uid_map.
    Returns a list of successfully saved Email objects and a list of errored email data.
    """
    successfully_saved_emails: List[Email] = []
    errored_emails_data: List[Dict[str, Any]] = []

    logger.info(f"Processing mailbox: {mailbox.email_address} (ID: {mailbox.id})")
    try:
        fetched_emails_data, new_uid_map = imap_service.fetch_emails_from_mailbox(mailbox)
    except ValueError as e:
        logger.error(f"IMAP configuration error for mailbox {mailbox.email_address}: {e}", exc_info=True)
        return [], []
    except ConnectionError as e:
        logger.error(f"IMAP connection error for mailbox {mailbox.email_address}: {e}", exc_info=True)
        return [], []
    except RuntimeError as e:
        logger.error(f"IMAP runtime error for mailbox {mailbox.email_address}: {e}", exc_info=True)
        return [], []
    except Exception as e:
        logger.error(f"Unexpected error fetching emails for {mailbox.email_address}: {e}", exc_info=True)
        return [], []

    logger.info(f"Fetched {len(fetched_emails_data)} email(s) from IMAP for {mailbox.email_address}")

    for email_data in fetched_emails_data:
        try:
            if not email_data.get("message_uid") or not email_data.get("folder_name"):
                logger.error(f"Essential data missing (UID or folder) for an email from {mailbox.email_address}. Skipping.")
                errored_emails_data.append({
                    "message_uid": email_data.get('message_uid'),
                    "error": "Essential data missing (UID or folder)"
                })
                continue

            existing_email = get_email_by_uid_folder_mailbox(
                db, str(email_data["message_uid"]), email_data["folder_name"], mailbox.id
            )
            if existing_email:
                logger.info(f"Duplicate email skipped: UID {email_data['message_uid']} in {email_data['folder_name']} for mailbox {mailbox.id}")
                continue

            if email_data.get("received_at_header") is None:
                logger.error(f"Email UID {email_data['message_uid']} for mailbox {mailbox.id} is missing 'received_at_header'. Saving as error_ingestion.")
                # This will likely fail if DB received_at_header is NOT NULL, caught by outer try-except
                saved_email = save_email_to_db(
                    db, email_data, mailbox.id,
                    processing_status='error_ingestion',
                    error_details="Missing or unparseable 'Date' header from email."
                )
                errored_emails_data.append({"db_email_id": saved_email.id, "error": "Missing received_at_header"})
                continue

            current_sender_address = email_data.get("sender_address")
            if is_sender_permanently_blocked(db, current_sender_address):
                logger.info(f"Sender {current_sender_address} is permanently blocked. Email UID {email_data['message_uid']} quarantined.")
                saved_email = save_email_to_db(
                    db, email_data, mailbox.id, processing_status='spam_quarantined'
                )
                continue

            saved_email_obj = save_email_to_db(db, email_data, mailbox.id, processing_status='new')
            successfully_saved_emails.append(saved_email_obj)

        except ValueError as ve: # Catch specific errors like missing received_at_header from save_email_to_db
            logger.error(f"Failed to save email UID {email_data.get('message_uid')} for mailbox {mailbox.id} due to validation: {ve}", exc_info=True)
            errored_emails_data.append({"message_uid": email_data.get('message_uid'), "error": f"Validation error: {str(ve)}"})
        except Exception as e: # Catch DB errors or other unexpected issues during individual email processing
            logger.error(f"Failed to save or process email UID {email_data.get('message_uid')} for mailbox {mailbox.id}: {e}", exc_info=True)
            error_description = f"Error processing/saving email: {str(e)}"
            # Try to save with error_ingestion status, this is a best effort.
            # This path is taken if, for example, received_at_header was None and save_email_to_db failed the INSERT.
            try:
                # Ensure email_data for error saving doesn't itself cause an error (e.g. if a key is missing)
                err_save_data = email_data.copy() # Work with a copy
                # If received_at_header was the problem, it must be handled for this error save:
                # EITHER make it nullable in DB OR provide a placeholder for error records OR omit it.
                # For now, we can't easily omit it without changing save_email_to_db structure.
                # Let's assume if we reach here due to received_at_header, it's already None.
                # The save_email_to_db will fail again if it's None and column is NOT NULL.
                # This highlights the need for `received_at_header` to be nullable.
                # For now, if it's None, this error save will also fail.

                if err_save_data.get("received_at_header") is None:
                     # This is the problematic scenario. If we can't save it with None, we log and skip.
                     logger.critical(f"Cannot save error record for UID {err_save_data.get('message_uid')} because received_at_header is None and DB column is NOT NULL.")
                     errored_emails_data.append({
                         "message_uid": err_save_data.get('message_uid'),
                         "error": f"Original error: {error_description}. Also, cannot save error record due to missing received_at_header."
                     })
                else:
                    saved_err_email = save_email_to_db(
                        db, err_save_data, mailbox.id,
                        processing_status='error_ingestion',
                        error_details=error_description[:1024]
                    )
                    errored_emails_data.append({"db_email_id": saved_err_email.id, "error": error_description})
            except Exception as e_save_err:
                logger.critical(f"Failed even to save email UID {email_data.get('message_uid')} with error status: {e_save_err}", exc_info=True)
                errored_emails_data.append({"message_uid": email_data.get('message_uid'), "error": f"Failed to save error record: {e_save_err}. Original error: {error_description}"})

    if fetched_emails_data or (new_uid_map and new_uid_map != (mailbox.last_checked_uid_map or {})):
        if new_uid_map:
            update_mailbox_last_checked_uids(db, mailbox.id, new_uid_map)

    logger.info(f"Finished processing for mailbox {mailbox.email_address}. Saved: {len(successfully_saved_emails)}, Errored: {len(errored_emails_data)}")
    return successfully_saved_emails, errored_emails_data

# Example usage
# if __name__ == '__main__':
#     # Basic logging for standalone script execution
#     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
#     db_session = SessionLocal()
#     try:
#         active_mailboxes = get_active_mailboxes(db_session)
#         logger.info(f"Found {len(active_mailboxes)} active mailboxes.")
#         for mbx in active_mailboxes:
#             logger.info(f"Processing: {mbx.email_address} (ID: {mbx.id})")
#             if mbx.imap_password_encrypted and mbx.imap_host:
#                 try:
#                     saved, errored = process_mailbox_emails(db_session, mbx)
#                     logger.info(f"  Saved {len(saved)} emails for {mbx.email_address}.")
#                     # for email_obj in saved:
#                     #     logger.debug(f"    - ID: {email_obj.id}, Subject: {email_obj.subject}")
#                     if errored:
#                         logger.warning(f"  Errored {len(errored)} emails for {mbx.email_address}.")
#                         # for err_info in errored:
#                         #     logger.debug(f"    - UID/ID: {err_info.get('message_uid') or err_info.get('db_email_id')}, Error: {err_info.get('error')}")
#                 except Exception as e:
#                     logger.error(f"  Error processing mailbox {mbx.email_address} during test: {e}", exc_info=True)
#             else:
#                 logger.warning(f"  Skipping mailbox {mbx.email_address} due to missing IMAP configuration for test.")
#     finally:
#         db_session.close()
