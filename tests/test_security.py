import pytest
from core.security import (
    generate_key_hex,
    encrypt_string,
    decrypt_string,
    encrypt_dict,
    decrypt_dict,
    encrypt_bytes,
    decrypt_bytes
)

def test_encryption_roundtrip():
    key = generate_key_hex()
    plaintext = "super-secret-password-123!"
    ciphertext = encrypt_string(plaintext, key=key)
    
    assert ciphertext != plaintext
    decrypted = decrypt_string(ciphertext, key=key)
    assert decrypted == plaintext

def test_dict_encryption_roundtrip():
    key = generate_key_hex()
    data = {
        "cookies": [
            {"name": "session_id", "value": "abc123xyz"},
            {"name": "auth_token", "value": "eyJhbGciOi..."}
        ],
        "origins": []
    }
    encrypted = encrypt_dict(data, key=key)
    decrypted = decrypt_dict(encrypted, key=key)
    assert decrypted == data

def test_tampered_ciphertext_fails():
    key = generate_key_hex()
    ciphertext = encrypt_string("confidential_data", key=key)
    # Tamper with ciphertext
    import base64
    raw = bytearray(base64.b64decode(ciphertext))
    raw[-1] ^= 0x01 # Flip last bit
    tampered = base64.b64encode(raw).decode("ascii")

    with pytest.raises(Exception):
        decrypt_string(tampered, key=key)

def test_invalid_key_length_rejected():
    with pytest.raises(ValueError):
        encrypt_string("test", key="short_key")

def test_bytes_encryption_roundtrip():
    key = generate_key_hex()
    data = b"raw binary secret \x00\xff\xfe"
    encrypted = encrypt_bytes(data, key=key)
    decrypted = decrypt_bytes(encrypted, key=key)
    assert decrypted == data
