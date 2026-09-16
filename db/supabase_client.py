import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from supabase import create_client, Client
from core.config import settings
from core.security import encrypt_string, decrypt_string, encrypt_dict, decrypt_dict

logger = logging.getLogger("digital-invoice-web.db")

class SupabaseService:
    def __init__(self):
        self._client: Optional[Client] = None
        self._init_client()

    def _init_client(self):
        if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
            try:
                self._client = create_client(
                    settings.SUPABASE_URL,
                    settings.SUPABASE_SERVICE_ROLE_KEY
                )
                logger.info("Supabase client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize Supabase client: {e}")
                self._client = None
        else:
            logger.warning("SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is not set. Database persistence will be disabled or mocked.")

    @property
    def client(self) -> Optional[Client]:
        if not self._client and settings.SUPABASE_URL and settings.SUPABASE_SERVICE_ROLE_KEY:
            self._init_client()
        return self._client

    async def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve tenant info and verify active status."""
        if not self.client:
            return None
        try:
            res = self.client.table("tenants").select("*").eq("id", tenant_id).execute()
            if res.data and len(res.data) > 0:
                return res.data[0]
            return None
        except Exception as e:
            logger.error(f"Error fetching tenant {tenant_id}: {e}")
            return None

    async def get_decrypted_credentials(self, tenant_id: str) -> Optional[Dict[str, str]]:
        """Retrieve and decrypt credentials for a tenant."""
        if not self.client:
            return None
        try:
            res = self.client.table("tenant_credentials").select("*").eq("tenant_id", tenant_id).execute()
            if not res.data or len(res.data) == 0:
                logger.warning(f"No credentials found for tenant {tenant_id}")
                return None
            record = res.data[0]
            email = decrypt_string(record["encrypted_email"])
            password = decrypt_string(record["encrypted_password"])
            return {
                "email": email,
                "password": password,
                "key_version": record.get("encryption_key_version", 1)
            }
        except Exception as e:
            logger.error(f"Error retrieving credentials for tenant {tenant_id}: {e}")
            return None

    async def get_tenant_id_by_url_token(self, url_token: str) -> Optional[str]:
        """
        Looks up tenants table by url_token, returns id (tenant_id) or None if
        not found / tenant.is_active is False. Single indexed query.
        """
        if not self.client or not url_token:
            return None
        try:
            res = self.client.table("tenants").select("id, is_active").eq("url_token", url_token).execute()
            if res.data and len(res.data) > 0:
                record = res.data[0]
                if record.get("is_active", False):
                    return record["id"]
            return None
        except Exception as e:
            logger.error(f"Error fetching tenant by url_token: {e}")
            return None

    async def rotate_url_token(self, tenant_id: str) -> str:
        """
        Generates secrets.token_urlsafe(24), updates tenants.url_token for that
        tenant_id, returns the new token. Retries once on unique-constraint collision.
        """
        if not self.client:
            raise RuntimeError("Supabase client is not configured")

        for attempt in range(2):
            new_token = secrets.token_urlsafe(24)
            try:
                self.client.table("tenants").update({
                    "url_token": new_token
                }).eq("id", tenant_id).execute()
                logger.info(f"Successfully rotated url_token for tenant {tenant_id}")
                return new_token
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"Collision or error rotating url_token for tenant {tenant_id}, retrying: {e}")
                    continue
                logger.error(f"Failed to rotate url_token for tenant {tenant_id}: {e}")
                raise

    async def save_tenant_credentials(
        self,
        tenant_id: str,
        company_name: str,
        email: str,
        password: str,
        key_version: Optional[int] = None,
        url_token: Optional[str] = None
    ) -> bool:
        """Create or update tenant and store encrypted credentials."""
        if not self.client:
            raise RuntimeError("Supabase client is not configured")
        
        kv = key_version or settings.CURRENT_KEY_VERSION
        encrypted_email = encrypt_string(email)
        encrypted_password = encrypt_string(password)

        try:
            # 1. Upsert tenant
            tenant_payload: Dict[str, Any] = {
                "id": tenant_id,
                "company_name": company_name,
                "is_active": True
            }
            if url_token:
                tenant_payload["url_token"] = url_token
            self.client.table("tenants").upsert(tenant_payload).execute()

            # 2. Upsert credentials
            self.client.table("tenant_credentials").upsert({
                "tenant_id": tenant_id,
                "encrypted_email": encrypted_email,
                "encrypted_password": encrypted_password,
                "encryption_key_version": kv,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }).execute()
            logger.info(f"Successfully saved credentials for tenant {tenant_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save credentials for tenant {tenant_id}: {e}")
            raise

    async def get_valid_session(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve non-expired Playwright storage_state for a tenant."""
        if not self.client:
            return None
        try:
            res = self.client.table("tenant_sessions").select("*").eq("tenant_id", tenant_id).execute()
            if not res.data or len(res.data) == 0:
                return None
            session = res.data[0]
            expires_at_str = session.get("expires_at")
            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                if datetime.now(timezone.utc) >= expires_at:
                    logger.info(f"Session for tenant {tenant_id} has expired")
                    return None
            
            raw_state = session.get("storage_state")
            if isinstance(raw_state, dict) and "encrypted_payload" in raw_state:
                # Decrypt storage state
                return decrypt_dict(raw_state["encrypted_payload"])
            elif isinstance(raw_state, dict):
                return raw_state
            return None
        except Exception as e:
            logger.error(f"Error fetching session for tenant {tenant_id}: {e}")
            return None

    async def save_session(self, tenant_id: str, storage_state: Dict[str, Any]) -> bool:
        """Save new Playwright storage_state for a tenant, encrypted at rest."""
        if not self.client:
            return False
        try:
            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(hours=settings.SESSION_TTL_HOURS)
            # Encrypt storage_state at rest
            encrypted_payload = encrypt_dict(storage_state)
            record = {
                "tenant_id": tenant_id,
                "storage_state": {"encrypted_payload": encrypted_payload},
                "last_used_at": now.isoformat(),
                "expires_at": expires_at.isoformat()
            }
            self.client.table("tenant_sessions").upsert(record).execute()
            logger.info(f"Saved session storage_state for tenant {tenant_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to save session for tenant {tenant_id}: {e}")
            return False

    async def invalidate_session(self, tenant_id: str) -> bool:
        """Delete or expire existing session for a tenant upon auth failure."""
        if not self.client:
            return False
        try:
            self.client.table("tenant_sessions").delete().eq("tenant_id", tenant_id).execute()
            logger.info(f"Invalidated session for tenant {tenant_id}")
            return True
        except Exception as e:
            logger.error(f"Error invalidating session for tenant {tenant_id}: {e}")
            return False

    async def log_tool_call(
        self,
        tenant_id: Optional[str],
        tool_name: str,
        status: str,
        duration_ms: int,
        error_detail: Optional[str] = None
    ) -> bool:
        """Record diagnostic tool call log."""
        if not self.client:
            return False
        try:
            self.client.table("tool_call_logs").insert({
                "tenant_id": tenant_id if tenant_id else None,
                "tool_name": tool_name,
                "status": status,
                "duration_ms": duration_ms,
                "error_detail": error_detail
            }).execute()
            return True
        except Exception as e:
            logger.warning(f"Could not write tool_call_log: {e}")
            return False

db_service = SupabaseService()
