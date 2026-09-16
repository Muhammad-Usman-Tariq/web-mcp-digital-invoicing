#!/usr/bin/env python3
"""
CLI Utility to safely onboard a tenant's credentials into Supabase.
Credentials are encrypted using AES-256-GCM before writing to the database.

Usage:
  python scripts/add_tenant.py --tenant-id <TENANT_ID> --company-name "Acme Corp" --email user@example.com --password mypass
"""

import sys
import os
import argparse
import asyncio
import getpass

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.config import settings
from db.supabase_client import db_service

async def main():
    parser = argparse.ArgumentParser(description="Securely onboard a tenant to digital-invoice-web.")
    parser.add_argument("--tenant-id", help="Tenant ID (must match the sub or tenant_id claim in Central Auth JWT)")
    parser.add_argument("--company-name", help="Company Name")
    parser.add_argument("--email", help="Login email for digitalinvoicingsoftware.com")
    parser.add_argument("--password", help="Login password for digitalinvoicingsoftware.com")
    args = parser.parse_args()

    if not settings.ENCRYPTION_MASTER_KEY:
        print("ERROR: ENCRYPTION_MASTER_KEY environment variable is not configured.")
        print("Run 'python scripts/generate_master_key.py' to generate one.")
        sys.exit(1)

    if not settings.SUPABASE_URL or not settings.SUPABASE_SERVICE_ROLE_KEY:
        print("ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is not configured in .env.")
        sys.exit(1)

    tenant_id = args.tenant_id or input("Enter Tenant ID (matching Central Auth JWT sub/tenant_id): ").strip()
    company_name = args.company_name or input("Enter Company Name: ").strip()
    email = args.email or input("Enter Portal Login Email: ").strip()
    password = args.password or getpass.getpass("Enter Portal Login Password: ").strip()

    if not tenant_id or not company_name or not email or not password:
        print("ERROR: All fields (tenant_id, company_name, email, password) are required.")
        sys.exit(1)

    print(f"\nEncrypting credentials with AES-256-GCM (Key version {settings.CURRENT_KEY_VERSION})...")
    try:
        await db_service.save_tenant_credentials(
            tenant_id=tenant_id,
            company_name=company_name,
            email=email,
            password=password,
            key_version=settings.CURRENT_KEY_VERSION
        )
        print(f"\nSUCCESS: Tenant '{company_name}' ({tenant_id}) successfully enrolled in Supabase!")
        print("Credentials have been securely encrypted and stored.")
    except Exception as e:
        print(f"\nFAILED to enroll tenant: {e}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
