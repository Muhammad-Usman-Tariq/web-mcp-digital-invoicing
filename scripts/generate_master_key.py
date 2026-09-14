#!/usr/bin/env python3
"""
Generate a cryptographically secure 32-byte (256-bit) AES master encryption key.
Outputs both Hex and Base64 representations suitable for the ENCRYPTION_MASTER_KEY env var.
"""

import os
import base64

def main():
    key_bytes = os.urandom(32)
    key_hex = key_bytes.hex()
    key_b64 = base64.b64encode(key_bytes).decode("ascii")

    print("\n=======================================================")
    print(" Digital-Invoice-Web: Master Encryption Key Generated")
    print("=======================================================\n")
    print(f"HEX Format (64 chars):\n  {key_hex}\n")
    print(f"Base64 Format (44 chars):\n  {key_b64}\n")
    print("Add this to your .env file or Coolify Environment Variables:")
    print(f'ENCRYPTION_MASTER_KEY="{key_hex}"\n')
    print("WARNING: Keep this key strictly confidential. Never commit to git.")
    print("=======================================================\n")

if __name__ == "__main__":
    main()
