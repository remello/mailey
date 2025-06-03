# app/api.py
from fastapi import FastAPI, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timezone # Ensure timezone is imported
from pydantic import EmailStr

from app import schemas, models # models refers to SQLAlchemy models
from app.db import get_db_session
from app.services import encryption_service # For password encryption
from app.config import settings
from app.api_helpers import get_api_key

app = FastAPI(title="Email Ingestor Management API", version="0.1.0")

# --- Mailbox Endpoints ---
@app.post("/mailboxes", response_model=schemas.MailboxResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_api_key)])
def create_mailbox(mailbox_in: schemas.MailboxCreate, db: Session = Depends(get_db_session)):
    db_mailbox = db.query(models.Mailbox).filter(models.Mailbox.email_address == mailbox_in.email_address).first()
    if db_mailbox:
        raise HTTPException(status_code=400, detail=f"Mailbox with email {mailbox_in.email_address} already exists.")

    encrypted_password = encryption_service.encrypt_password(mailbox_in.imap_password)

    new_mailbox = models.Mailbox(
        email_address=mailbox_in.email_address,
        imap_host=mailbox_in.imap_host,
        imap_port=mailbox_in.imap_port,
        imap_login=mailbox_in.imap_login,
        imap_password_encrypted=encrypted_password,
        monitored_folders=mailbox_in.monitored_folders,
        is_active=mailbox_in.is_active
    )
    db.add(new_mailbox)
    db.commit()
    db.refresh(new_mailbox)
    return new_mailbox

@app.get("/mailboxes", response_model=List[schemas.MailboxResponse], dependencies=[Depends(get_api_key)])
def list_mailboxes(skip: int = 0, limit: int = 100, db: Session = Depends(get_db_session)):
    mailboxes = db.query(models.Mailbox).offset(skip).limit(limit).all()
    return mailboxes

@app.get("/mailboxes/{mailbox_id}", response_model=schemas.MailboxResponse, dependencies=[Depends(get_api_key)])
def get_mailbox(mailbox_id: int, db: Session = Depends(get_db_session)):
    db_mailbox = db.query(models.Mailbox).filter(models.Mailbox.id == mailbox_id).first()
    if not db_mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found.")
    return db_mailbox

# --- BlockedSender Endpoints ---
@app.post("/blocked_senders", response_model=schemas.BlockedSenderResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(get_api_key)])
def create_blocked_sender(sender_in: schemas.BlockedSenderCreate, db: Session = Depends(get_db_session)):
    db_sender = db.query(models.BlockedSender).filter(models.BlockedSender.sender_address == sender_in.sender_address).first()
    if db_sender:
        raise HTTPException(status_code=400, detail=f"Sender {sender_in.sender_address} already in blocklist.")

    new_sender = models.BlockedSender(
        sender_address=sender_in.sender_address,
        reason=sender_in.reason,
        is_permanently_blocked=True, # Default to permablock on manual add via API
        blocked_at=datetime.now(timezone.utc) # Set blocked_at on creation using timezone.utc
    )
    db.add(new_sender)
    db.commit()
    db.refresh(new_sender)
    return new_sender

# --- Mailbox Endpoints (Continued) ---
@app.put("/mailboxes/{mailbox_id}", response_model=schemas.MailboxResponse, dependencies=[Depends(get_api_key)])
def update_mailbox(mailbox_id: int, mailbox_in: schemas.MailboxUpdate, db: Session = Depends(get_db_session)):
    db_mailbox = db.query(models.Mailbox).filter(models.Mailbox.id == mailbox_id).first()
    if not db_mailbox:
        raise HTTPException(status_code=404, detail="Mailbox not found.")

    update_data = mailbox_in.dict(exclude_unset=True)

    if "imap_password" in update_data and update_data["imap_password"] is not None:
        encrypted_password = encryption_service.encrypt_password(update_data["imap_password"])
        db_mailbox.imap_password_encrypted = encrypted_password
        del update_data["imap_password"] # Remove plain password from update_data

    for key, value in update_data.items():
        setattr(db_mailbox, key, value)

    db_mailbox.updated_at = datetime.now(timezone.utc) # Manually update updated_at
    db.add(db_mailbox)
    db.commit()
    db.refresh(db_mailbox)
    return db_mailbox

# --- BlockedSender Endpoints (Continued) ---
@app.get("/blocked_senders", response_model=List[schemas.BlockedSenderResponse], dependencies=[Depends(get_api_key)])
def list_blocked_senders(skip: int = 0, limit: int = 100, db: Session = Depends(get_db_session)):
    senders = db.query(models.BlockedSender).offset(skip).limit(limit).all()
    return senders

@app.get("/blocked_senders/address/{sender_address}", response_model=schemas.BlockedSenderResponse, dependencies=[Depends(get_api_key)])
def get_blocked_sender_by_address(sender_address: EmailStr, db: Session = Depends(get_db_session)):
    # FastAPI/Pydantic should handle EmailStr validation
    db_sender = db.query(models.BlockedSender).filter(models.BlockedSender.sender_address == sender_address).first()
    if not db_sender:
        raise HTTPException(status_code=404, detail=f"Sender with address {sender_address} not found in blocklist.")
    return db_sender

@app.get("/blocked_senders/id/{sender_id}", response_model=schemas.BlockedSenderResponse, dependencies=[Depends(get_api_key)])
def get_blocked_sender_by_id(sender_id: int, db: Session = Depends(get_db_session)):
    db_sender = db.query(models.BlockedSender).filter(models.BlockedSender.id == sender_id).first()
    if not db_sender:
        raise HTTPException(status_code=404, detail=f"Sender with ID {sender_id} not found in blocklist.")
    return db_sender

@app.delete("/blocked_senders/address/{sender_address}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_api_key)])
def delete_blocked_sender_by_address(sender_address: EmailStr, db: Session = Depends(get_db_session)):
    db_sender = db.query(models.BlockedSender).filter(models.BlockedSender.sender_address == sender_address).first()
    if not db_sender:
        raise HTTPException(status_code=404, detail=f"Sender with address {sender_address} not found in blocklist for deletion.")

    db.delete(db_sender)
    db.commit()
    return None # Return None for 204 No Content

@app.delete("/blocked_senders/id/{sender_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_api_key)])
def delete_blocked_sender_by_id(sender_id: int, db: Session = Depends(get_db_session)):
    db_sender = db.query(models.BlockedSender).filter(models.BlockedSender.id == sender_id).first()
    if not db_sender:
        raise HTTPException(status_code=404, detail=f"Sender with ID {sender_id} not found in blocklist for deletion.")

    db.delete(db_sender)
    db.commit()
    return None

# To run this API (example, actual command might be in a Procfile or run script):
# uvicorn app.api:app --reload --port 8000
