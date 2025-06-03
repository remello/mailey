# app/config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env file if it exists
# This is particularly useful for local development
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
if os.path.exists(dotenv_path):
    load_dotenv(dotenv_path)

class Settings:
    # Database Configuration
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://user:password@localhost:5432/email_ingestor_db")

    # RabbitMQ Configuration
    RABBITMQ_URL: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    RABBITMQ_EMAIL_PROCESSING_QUEUE: str = os.getenv("RABBITMQ_EMAIL_PROCESSING_QUEUE", "email_processing_queue")

    # IMAP Service Configuration
    CHECK_INTERVAL_MINUTES: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "5")) # Interval in minutes to check mailboxes

    # Logging Configuration
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper() # e.g., DEBUG, INFO, WARNING, ERROR

    # (Optional) Encryption key for IMAP passwords - should be securely managed
    # For simplicity in this phase, we might just use it directly, but in production,
    # this should come from a secure source (e.g., HashiCorp Vault, AWS KMS)
    # Ensure this is a 32-byte URL-safe base64-encoded key if using Fernet
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "your_default_fernet_key_32_bytes") # Placeholder, MUST be changed

    # API Configuration (if API is implemented)
    API_BASE_URL: str = os.getenv("API_BASE_URL", "/api/v1")
    # A simple API key for demonstration. In production, use a more robust auth mechanism.
    API_KEY: str = os.getenv("API_KEY", "default_secret_api_key")


settings = Settings()

# Example of how to use:
# from app.config import settings
# print(settings.DATABASE_URL)
