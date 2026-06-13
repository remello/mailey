# app/schemas.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, EmailStr, Json, validator
from datetime import datetime

# Mailbox Schemas
class MailboxBase(BaseModel):
    email_address: EmailStr
    imap_host: str
    imap_port: int
    imap_login: str
    monitored_folders: List[str] = ["INBOX"]
    is_active: bool = True

class MailboxCreate(MailboxBase):
    imap_password: str # Plain password, will be encrypted by the API

class MailboxUpdate(BaseModel):
    email_address: Optional[EmailStr] = None
    imap_host: Optional[str] = None
    imap_port: Optional[int] = None
    imap_login: Optional[str] = None
    imap_password: Optional[str] = None # For updating password, plain text
    monitored_folders: Optional[List[str]] = None
    is_active: Optional[bool] = None
    last_checked_uid_map: Optional[Dict[str, int]] = None


class MailboxResponse(MailboxBase):
    id: int
    # Exclude imap_password_encrypted for security
    last_checked_uid_map: Optional[Dict[str, int]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True

# BlockedSender Schemas
class BlockedSenderBase(BaseModel):
    sender_address: EmailStr
    reason: Optional[str] = None

class BlockedSenderCreate(BlockedSenderBase):
    pass

class BlockedSenderUpdate(BaseModel): # If needed, but current spec is just add/delete
    reason: Optional[str] = None
    spam_strike_count: Optional[int] = None
    is_permanently_blocked: Optional[bool] = None


class BlockedSenderResponse(BlockedSenderBase):
    id: int
    spam_strike_count: int
    first_strike_at: Optional[datetime] = None
    last_strike_at: Optional[datetime] = None
    blocked_at: Optional[datetime] = None
    is_permanently_blocked: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        orm_mode = True
