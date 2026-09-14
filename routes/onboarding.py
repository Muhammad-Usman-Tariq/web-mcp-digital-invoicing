"""
Self-Service Onboarding Web UI Routes for digital-invoice-web.

Enables tenants to:
1. Authenticate via Central Auth OAuth (establishing a cryptographically verified tenant_id).
2. Configure and securely store their Digital Invoicing Software portal credentials (encrypted with AES-256-GCM).
3. Test their live headless browser connection directly from the browser.
4. Access copyable MCP server connection URLs and per-LLM setup guides.
"""

import time
import logging
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

import jwt
from jwt import PyJWKClient
from fastapi import APIRouter, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.config import settings
from core.context import set_current_tenant_id, set_current_auth_claims, clear_context
from db.supabase_client import db_service
from tools.foundation import check_login_status

logger = logging.getLogger("digital-invoice-web.onboarding")

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])
templates = Jinja2Templates(directory="templates")

# Cached JWKS client for verifying Central Auth JWT tokens
_jwks_client: Optional[PyJWKClient] = None

def get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(settings.JWKS_URI, cache_keys=True, max_cached_keys=16)
    return _jwks_client

# In-memory sliding window rate limiter: key -> list of timestamp floats
_rate_limits: Dict[str, List[float]] = {}
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes

def is_rate_limited(key: str) -> bool:
    """Check if key has exceeded MAX_ATTEMPTS in the last WINDOW_SECONDS."""
    now = time.time()
    timestamps = _rate_limits.get(key, [])
    # Filter out timestamps older than window
    timestamps = [ts for ts in timestamps if now - ts < WINDOW_SECONDS]
    _rate_limits[key] = timestamps
    if len(timestamps) >= MAX_ATTEMPTS:
        return True
    timestamps.append(now)
    return False

def get_client_ip(request: Request) -> str:
    """Extract client IP safely from request headers or client host."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"

def verify_onboarding_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify RS256 token against Central Auth JWKS and audience.
    Returns decoded claims dict on success, None on failure.
    """
    if not token or not token.strip():
        return None
    token = token.strip()
    try:
        jwks = get_jwks_client()
        signing_key = jwks.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.MCP_AUTH_AUDIENCE,
            leeway=60
        )
        return payload
    except Exception as e:
        logger.debug(f"Token verification failed: {e}")
        return None

def extract_token_claims_from_request(request: Request) -> Optional[Dict[str, Any]]:
    """
    Extract token from session cookie, Authorization header, or query param.
    Verifies token claims and returns them.
    """
    token = request.cookies.get("onboarding_token")

    if not token:
        auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
        if auth_header:
            parts = auth_header.split()
            if len(parts) == 2 and parts[0].lower() == "bearer":
                token = parts[1].strip()

    if not token and "token" in request.query_params:
        token = request.query_params["token"].strip()

    if not token:
        return None

    return verify_onboarding_token(token)

def resolve_tenant_id_from_claims(claims: Dict[str, Any]) -> str:
    """Extract tenant_id or sub from verified claims."""
    return str(claims.get("tenant_id") or claims.get("tenant") or claims.get("sub") or "")

def mask_email(email: str) -> str:
    """Mask email for privacy, e.g. a***@example.com."""
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"

def build_central_auth_url(request: Request) -> str:
    """Construct Central Auth OAuth authorization URL if possible."""
    try:
        parsed = urlparse(settings.JWKS_URI)
        auth_base = f"{parsed.scheme}://{parsed.netloc}"
        redirect_uri = f"{str(request.base_url).rstrip('/')}/onboarding/callback"
        return (
            f"{auth_base}/authorize?"
            f"response_type=code&client_id={settings.MCP_AUTH_AUDIENCE}&"
            f"redirect_uri={redirect_uri}&scope=mcp:access"
        )
    except Exception:
        return ""


# -------------------------------------------------------------------------
# Step 1: Authentication & Tenant Identification
# -------------------------------------------------------------------------

@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def onboarding_index(request: Request):
    """
    Entrypoint: Checks for valid Central Auth session.
    If authenticated, redirects to /onboarding/credentials.
    If not, redirects to /onboarding/login.
    """
    claims = extract_token_claims_from_request(request)
    if not claims:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    tenant_id = resolve_tenant_id_from_claims(claims)
    if not tenant_id:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    return RedirectResponse(url="/onboarding/credentials", status_code=status.HTTP_302_FOUND)


@router.get("/login", response_class=HTMLResponse)
async def onboarding_login_page(request: Request):
    """
    Login page: Prompts user to log in via Central Auth or enter a valid JWT.
    """
    # If already authenticated, redirect to credentials
    claims = extract_token_claims_from_request(request)
    if claims and resolve_tenant_id_from_claims(claims):
        return RedirectResponse(url="/onboarding/credentials", status_code=status.HTTP_302_FOUND)

    # Check if query parameter has a token
    query_token = request.query_params.get("token")
    if query_token:
        verified_claims = verify_onboarding_token(query_token)
        if verified_claims and resolve_tenant_id_from_claims(verified_claims):
            response = RedirectResponse(url="/onboarding/credentials", status_code=status.HTTP_302_FOUND)
            response.set_cookie(
                key="onboarding_token",
                value=query_token.strip(),
                httponly=True,
                samesite="lax",
                secure=request.url.scheme == "https",
                max_age=86400 * 7
            )
            return response

    auth_url = build_central_auth_url(request)
    return templates.TemplateResponse(request=request, name="onboarding/login.html", context={
        "auth_url": auth_url,
        "expected_audience": settings.MCP_AUTH_AUDIENCE,
        "error": None,
        "info": None,
        "tenant_id": None
    })


@router.post("/login", response_class=HTMLResponse)
async def onboarding_login_submit(request: Request, token: str = Form(...)):
    """
    Handles manual token verification and sets HTTP-only session cookie.
    """
    ip = get_client_ip(request)
    if is_rate_limited(f"login:{ip}"):
        return templates.TemplateResponse(request=request, name="onboarding/login.html", context={
            "auth_url": build_central_auth_url(request),
            "expected_audience": settings.MCP_AUTH_AUDIENCE,
            "error": "Too many login attempts. Please wait a few minutes and try again.",
            "info": None,
            "tenant_id": None
        }, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    verified_claims = verify_onboarding_token(token)
    if not verified_claims:
        return templates.TemplateResponse(request=request, name="onboarding/login.html", context={
            "auth_url": build_central_auth_url(request),
            "expected_audience": settings.MCP_AUTH_AUDIENCE,
            "error": "Invalid or expired token. Ensure it is signed by Central Auth and targeted to audience: " + settings.MCP_AUTH_AUDIENCE,
            "info": None,
            "tenant_id": None
        }, status_code=status.HTTP_400_BAD_REQUEST)

    tenant_id = resolve_tenant_id_from_claims(verified_claims)
    if not tenant_id:
        return templates.TemplateResponse(request=request, name="onboarding/login.html", context={
            "auth_url": build_central_auth_url(request),
            "expected_audience": settings.MCP_AUTH_AUDIENCE,
            "error": "Token is missing required tenant identity claim ('tenant_id' or 'sub').",
            "info": None,
            "tenant_id": None
        }, status_code=status.HTTP_400_BAD_REQUEST)

    response = RedirectResponse(url="/onboarding/credentials", status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        key="onboarding_token",
        value=token.strip(),
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=86400 * 7
    )
    return response


@router.get("/callback", response_class=HTMLResponse)
async def onboarding_oauth_callback(request: Request):
    """
    Handles OAuth 2.1 authorization code redirect from Central Auth.
    """
    code = request.query_params.get("code")
    token = request.query_params.get("access_token")

    if token:
        verified_claims = verify_onboarding_token(token)
        if verified_claims and resolve_tenant_id_from_claims(verified_claims):
            response = RedirectResponse(url="/onboarding/credentials", status_code=status.HTTP_302_FOUND)
            response.set_cookie(
                key="onboarding_token",
                value=token.strip(),
                httponly=True,
                samesite="lax",
                secure=request.url.scheme == "https",
                max_age=86400 * 7
            )
            return response

    info_msg = (
        f"Authorization code '{code[:8]}...' received. If your client did not issue an immediate token, paste your access token below."
        if code
        else "OAuth authorization received. If your client did not issue an immediate token, paste your access token below."
    )
    return templates.TemplateResponse(request=request, name="onboarding/login.html", context={
        "auth_url": build_central_auth_url(request),
        "expected_audience": settings.MCP_AUTH_AUDIENCE,
        "error": None,
        "info": info_msg,
        "tenant_id": None
    })


@router.get("/logout")
async def onboarding_logout():
    """Clear onboarding session cookie and redirect to login."""
    response = RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="onboarding_token")
    return response


# -------------------------------------------------------------------------
# Step 2: Credential Configuration & Connection Testing
# -------------------------------------------------------------------------

@router.get("/credentials", response_class=HTMLResponse)
async def onboarding_credentials_page(request: Request):
    """
    Renders credential submission form for the verified tenant.
    Never lets user specify or override tenant_id.
    """
    claims = extract_token_claims_from_request(request)
    if not claims:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    tenant_id = resolve_tenant_id_from_claims(claims)
    if not tenant_id:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    # Check if tenant credentials already exist in database
    existing_tenant = None
    form_data = {"company_name": "", "email": ""}
    try:
        tenant_rec = await db_service.get_tenant(tenant_id)
        if tenant_rec:
            company_name = tenant_rec.get("company_name", "")
            form_data["company_name"] = company_name

            creds = await db_service.get_decrypted_credentials(tenant_id)
            if creds:
                masked = mask_email(creds.get("email", ""))
                existing_tenant = {
                    "company_name": company_name,
                    "email": masked,
                    "updated_at": tenant_rec.get("updated_at")
                }
                form_data["email"] = creds.get("email", "")
    except Exception as e:
        logger.warning(f"Failed to inspect existing tenant record for {tenant_id}: {e}")

    return templates.TemplateResponse(request=request, name="onboarding/credentials.html", context={
        "tenant_id": tenant_id,
        "existing_tenant": existing_tenant,
        "form_data": form_data,
        "success_msg": None,
        "error_msg": None
    })


@router.post("/credentials", response_class=HTMLResponse)
async def onboarding_credentials_submit(
    request: Request,
    company_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):
    """
    Saves encrypted credentials in Supabase.
    Rate-limited and strictly scoped to verified tenant_id from claims.
    Never logs or leaks submitted passwords.
    """
    claims = extract_token_claims_from_request(request)
    if not claims:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    tenant_id = resolve_tenant_id_from_claims(claims)
    if not tenant_id:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    ip = get_client_ip(request)
    if is_rate_limited(f"creds:{tenant_id}:{ip}"):
        return templates.TemplateResponse(request=request, name="onboarding/credentials.html", context={
            "tenant_id": tenant_id,
            "existing_tenant": None,
            "form_data": {"company_name": company_name, "email": email},
            "success_msg": None,
            "error_msg": "Too many credential submissions. Please wait a few minutes before trying again."
        }, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    if not company_name.strip() or not email.strip() or not password:
        return templates.TemplateResponse(request=request, name="onboarding/credentials.html", context={
            "tenant_id": tenant_id,
            "existing_tenant": None,
            "form_data": {"company_name": company_name, "email": email},
            "success_msg": None,
            "error_msg": "All fields (Company Name, Email, Password) are required."
        }, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        # Re-use existing db_service.save_tenant_credentials (no duplicate encryption logic)
        await db_service.save_tenant_credentials(
            tenant_id=tenant_id,
            company_name=company_name.strip(),
            email=email.strip(),
            password=password,
            key_version=settings.CURRENT_KEY_VERSION
        )

        logger.info(f"Onboarding: Successfully updated credentials for tenant {tenant_id} ({company_name})")

        existing_tenant = {
            "company_name": company_name.strip(),
            "email": mask_email(email.strip()),
            "updated_at": "Just now"
        }

        return templates.TemplateResponse(request=request, name="onboarding/credentials.html", context={
            "tenant_id": tenant_id,
            "existing_tenant": existing_tenant,
            "form_data": {"company_name": company_name, "email": email},
            "success_msg": "Credentials successfully encrypted with AES-256-GCM and saved to database!",
            "error_msg": None
        })
    except Exception as e:
        logger.error(f"Onboarding: Failed to save credentials for tenant {tenant_id}: {type(e).__name__}")
        return templates.TemplateResponse(request=request, name="onboarding/credentials.html", context={
            "tenant_id": tenant_id,
            "existing_tenant": None,
            "form_data": {"company_name": company_name, "email": email},
            "success_msg": None,
            "error_msg": f"Failed to save credentials: {str(e)}"
        }, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/test-connection")
async def onboarding_test_connection(request: Request):
    """
    Triggers live headless browser session verification for the calling tenant.
    Rate-limited and calls existing check_login_status() tool directly.
    """
    claims = extract_token_claims_from_request(request)
    if not claims:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"success": False, "error": "Unauthorized. Please log in first."}
        )

    tenant_id = resolve_tenant_id_from_claims(claims)
    if not tenant_id:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"success": False, "error": "No verified tenant identity found."}
        )

    ip = get_client_ip(request)
    if is_rate_limited(f"test_conn:{tenant_id}:{ip}"):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"success": False, "error": "Rate limit reached. Please wait 5 minutes before testing again."}
        )

    # Set contextvars for check_login_status
    set_current_tenant_id(tenant_id)
    set_current_auth_claims(claims)
    try:
        # Re-use existing check_login_status tool logic
        tool_result = await check_login_status()
        if not tool_result.get("success"):
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "success": False,
                    "is_logged_in": False,
                    "error": tool_result.get("error", "Login check returned an error.")
                }
            )

        data = tool_result.get("data", {})
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "is_logged_in": bool(data.get("is_logged_in")),
                "current_url": data.get("current_url"),
                "is_on_dashboard": data.get("is_on_dashboard"),
                "page_title": data.get("page_title")
            }
        )
    except Exception as e:
        logger.error(f"Onboarding test-connection failed for tenant {tenant_id}: {type(e).__name__}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "is_logged_in": False,
                "error": f"Connection check encountered an error: {str(e)}"
            }
        )
    finally:
        clear_context()


# -------------------------------------------------------------------------
# Step 3 & 4: MCP Connection Info & Per-LLM Client Guides
# -------------------------------------------------------------------------

@router.get("/connect", response_class=HTMLResponse)
async def onboarding_connect_page(request: Request):
    """
    Renders the MCP connection endpoint and per-LLM setup guides.
    """
    claims = extract_token_claims_from_request(request)
    if not claims:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    tenant_id = resolve_tenant_id_from_claims(claims)
    if not tenant_id:
        return RedirectResponse(url="/onboarding/login", status_code=status.HTTP_302_FOUND)

    # Compute live external base URL and MCP server URL
    base_url = str(request.base_url).rstrip("/")
    # If served behind a reverse proxy forwarding https
    if request.headers.get("x-forwarded-proto") == "https" and base_url.startswith("http://"):
        base_url = "https://" + base_url[7:]

    mcp_server_url = f"{base_url}/mcp"

    return templates.TemplateResponse(request=request, name="onboarding/connect.html", context={
        "tenant_id": tenant_id,
        "base_url": base_url,
        "mcp_server_url": mcp_server_url
    })
