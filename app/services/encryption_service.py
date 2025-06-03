# app/services/encryption_service.py
from cryptography.fernet import Fernet, InvalidToken
from app.config import settings
import logging

logger = logging.getLogger(__name__)

# Ensure the key is bytes
_key = settings.ENCRYPTION_KEY.encode()
_cipher_suite = Fernet(_key)

def encrypt_password(password: str) -> str:
    """Encrypts a password using Fernet encryption."""
    if not password:
        return ""
    encrypted_text = _cipher_suite.encrypt(password.encode())
    return encrypted_text.decode()

def decrypt_password(encrypted_password: str) -> str:
    """Decrypts a password using Fernet encryption."""
    if not encrypted_password:
        return ""
    try:
        decrypted_text = _cipher_suite.decrypt(encrypted_password.encode())
        return decrypted_text.decode()
    except InvalidToken:
        # Handle cases where the token is invalid (e.g., wrong key, corrupted data)
        # Log this error appropriately in a real application
        logger.error("Failed to decrypt password. Invalid token or key.", exc_info=True)
        # Depending on policy, either raise an exception or return an empty string/None
        raise ValueError("Decryption failed due to invalid token or key.")

# Example Usage (for testing this module directly):
# if __name__ == '__main__':
#     logging.basicConfig(level=logging.DEBUG) # Basic logging for test
#     original_pw = "mysecretpassword"
#     encrypted = encrypt_password(original_pw)
#     logger.info(f"Original: {original_pw}")
#     logger.info(f"Encrypted: {encrypted}")
#     decrypted = decrypt_password(encrypted)
#     logger.info(f"Decrypted: {decrypted}")
#     # Test with a bad token
#     try:
#         decrypt_password("bad_encrypted_string")
#     except ValueError as e:
#         logger.error(f"Test decryption error: {e}", exc_info=True)
