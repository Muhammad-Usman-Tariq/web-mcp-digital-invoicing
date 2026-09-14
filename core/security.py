import os
import json
import base64
from typing import Dict, Any, Union
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .config import settings

def _get_raw_key(key_input: Union[str, bytes, None] = None) -> bytes:
    """Resolve key input to a 32-byte binary key suitable for AES-256."""
    key = key_input or settings.ENCRYPTION_MASTER_KEY
    if not key:
        raise ValueError("ENCRYPTION_MASTER_KEY is not set or empty")

    if isinstance(key, bytes):
        raw_key = key
    elif isinstance(key, str):
        key = key.strip()
        # Check if 64-char hex
        if len(key) == 64 and all(c in "0123456789abcdefABCDEF" for c in key):
            raw_key = bytes.fromhex(key)
        else:
            try:
                # Check if base64 encoded
                raw_key = base64.b64decode(key)
            except Exception:
                raw_key = key.encode("utf-8")

    if len(raw_key) != 32:
        raise ValueError(
            f"Invalid key length: {len(raw_key)} bytes. AES-256 requires exactly 32 bytes (64 hex characters or 44 base64 chars)."
        )
    return raw_key

def encrypt_bytes(plaintext_bytes: bytes, key: Union[str, bytes, None] = None) -> str:
    """Encrypt bytes using AES-256-GCM with a random 12-byte nonce."""
    raw_key = _get_raw_key(key)
    aesgcm = AESGCM(raw_key)
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)
    # Combine nonce + ciphertext (which contains the 16-byte auth tag)
    payload = nonce + ciphertext
    return base64.b64encode(payload).decode("ascii")

def decrypt_bytes(encrypted_b64: str, key: Union[str, bytes, None] = None) -> bytes:
    """Decrypt base64-encoded AES-256-GCM payload."""
    raw_key = _get_raw_key(key)
    payload = base64.b64decode(encrypted_b64.encode("ascii"))
    if len(payload) < 28: # 12 bytes nonce + at least 16 bytes tag
        raise ValueError("Ciphertext payload is too short to be valid AES-GCM data")
    nonce = payload[:12]
    ciphertext = payload[12:]
    aesgcm = AESGCM(raw_key)
    return aesgcm.decrypt(nonce, ciphertext, None)

def encrypt_string(plaintext: str, key: Union[str, bytes, None] = None) -> str:
    """Encrypt UTF-8 string to base64 payload."""
    return encrypt_bytes(plaintext.encode("utf-8"), key)

def decrypt_string(encrypted_b64: str, key: Union[str, bytes, None] = None) -> str:
    """Decrypt base64 payload to UTF-8 string."""
    decrypted_bytes = decrypt_bytes(encrypted_b64, key)
    return decrypted_bytes.decode("utf-8")

def encrypt_dict(data: Dict[str, Any], key: Union[str, bytes, None] = None) -> str:
    """Serialize and encrypt a dictionary (e.g. Playwright storage_state)."""
    serialized = json.dumps(data)
    return encrypt_string(serialized, key)

def decrypt_dict(encrypted_b64: str, key: Union[str, bytes, None] = None) -> Dict[str, Any]:
    """Decrypt and parse a dictionary."""
    decrypted_str = decrypt_string(encrypted_b64, key)
    return json.loads(decrypted_str)

def generate_key_hex() -> str:
    """Generate a random 32-byte hex string (64 characters)."""
    return os.urandom(32).hex()
