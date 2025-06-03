from sqlalchemy import (
    create_engine, Column, Integer, String, Boolean, JSON, TIMESTAMP, TEXT, ForeignKey, Index, func, VARCHAR
)
from sqlalchemy.orm import relationship, declarative_base
from sqlalchemy.dialects.postgresql import JSONB

Base = declarative_base()

class Mailbox(Base):
    __tablename__ = "mailboxes"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    email_address = Column(VARCHAR, unique=True, nullable=False)
    imap_host = Column(VARCHAR, nullable=False)
    imap_port = Column(Integer, nullable=False)
    imap_login = Column(VARCHAR, nullable=False)
    imap_password_encrypted = Column(VARCHAR, nullable=False)
    monitored_folders = Column(JSONB, nullable=False, default=lambda: ["INBOX"]) # e.g., ["INBOX", "Orders"]
    is_active = Column(Boolean, default=True, nullable=False)
    last_checked_uid_map = Column(JSONB, nullable=True) # e.g., {"INBOX": 12345, "Orders": 67890}
    created_at = Column(TIMESTAMP(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    emails = relationship("Email", back_populates="mailbox")

    __table_args__ = (
        Index('idx_mailboxes_email_address', 'email_address', unique=True),
    )

class Email(Base):
    __tablename__ = "emails"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    mailbox_id = Column(Integer, ForeignKey("mailboxes.id"), nullable=False)
    message_uid = Column(VARCHAR, nullable=False) # UID within the folder
    folder_name = Column(VARCHAR, nullable=False)
    message_id_header = Column(VARCHAR, nullable=True) # Message-ID header
    sender_address = Column(VARCHAR, nullable=False)
    recipient_address = Column(VARCHAR, nullable=False)
    subject = Column(TEXT, nullable=True)
    body_html = Column(TEXT, nullable=True)
    body_text = Column(TEXT, nullable=True)
    received_at_header = Column(TIMESTAMP(timezone=True), nullable=True) # Date header from email
    ingested_at = Column(TIMESTAMP(timezone=True), default=func.now(), nullable=False)
    raw_headers = Column(JSONB, nullable=True)
    processing_status = Column(VARCHAR, default='new', nullable=False) # new, spam_quarantined, queued_for_deepseek, error_ingestion
    apt_from_recipient_address = Column(VARCHAR(20), nullable=True) # Increased length slightly for apt+suffix
    error_details = Column(TEXT, nullable=True)
    hash_body_text = Column(VARCHAR(64), nullable=True) # SHA256 hash

    mailbox = relationship("Mailbox", back_populates="emails")

    __table_args__ = (
        Index('idx_emails_mailbox_folder_uid', 'mailbox_id', 'folder_name', 'message_uid', unique=True),
        Index('idx_emails_processing_status', 'processing_status'),
        Index('idx_emails_sender_address', 'sender_address'), # For quick checks against blocked_senders
        Index('idx_emails_received_at_header', 'received_at_header'),
        Index('idx_emails_hash_body_text', 'hash_body_text'),
    )

class BlockedSender(Base):
    __tablename__ = "blocked_senders"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    sender_address = Column(VARCHAR, unique=True, nullable=False)
    reason = Column(TEXT, nullable=True)
    spam_strike_count = Column(Integer, default=0, nullable=False)
    first_strike_at = Column(TIMESTAMP(timezone=True), nullable=True)
    last_strike_at = Column(TIMESTAMP(timezone=True), nullable=True)
    blocked_at = Column(TIMESTAMP(timezone=True), nullable=True)
    is_permanently_blocked = Column(Boolean, default=False, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), default=func.now(), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        Index('idx_blocked_senders_sender_address', 'sender_address', unique=True),
    )

# Example of how to create the engine (not for this file, but for context)
# from sqlalchemy import create_engine
# DATABASE_URL = "postgresql://user:password@host:port/database"
# engine = create_engine(DATABASE_URL)
# Base.metadata.create_all(engine) # This should be handled by Alembic
