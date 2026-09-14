from contextvars import ContextVar
from typing import Dict, Any, Optional

# Asyncio-safe context variables
_current_tenant_id: ContextVar[str] = ContextVar("current_tenant_id", default="")
_current_auth_claims: ContextVar[Dict[str, Any]] = ContextVar("current_auth_claims", default={})

def get_current_tenant_id() -> str:
    """Retrieve the verified tenant_id for the current request context."""
    tenant_id = _current_tenant_id.get()
    if not tenant_id:
        # Fallback to claims check if tenant_id wasn't populated directly
        claims = _current_auth_claims.get()
        tenant_id = claims.get("tenant_id") or claims.get("tenant") or claims.get("sub", "")
    return tenant_id

def set_current_tenant_id(tenant_id: str) -> None:
    """Set the verified tenant_id in the current request context."""
    _current_tenant_id.set(tenant_id)

def get_current_auth_claims() -> Dict[str, Any]:
    """Retrieve the full decoded JWT claims for the current request."""
    return _current_auth_claims.get()

def set_current_auth_claims(claims: Dict[str, Any]) -> None:
    """Set the decoded JWT claims in the current request context."""
    _current_auth_claims.set(claims)
    # Automatically update tenant_id if present in claims
    tenant_id = claims.get("tenant_id") or claims.get("tenant") or claims.get("sub", "")
    if tenant_id:
        _current_tenant_id.set(str(tenant_id))

def clear_context() -> None:
    """Reset context for cleanup."""
    _current_tenant_id.set("")
    _current_auth_claims.set({})
