"""
Self-Service Onboarding Web UI Routes for digital-invoice-web.

Enables companies to:
1. Submit their Digital Invoicing Software portal credentials (saved and encrypted with AES-256-GCM).
2. View their MCP Server URL and per-LLM connection instructions (Central Auth manages all LLM client authentication).
3. Test their portal connection directly via the headless browser check.

Contains business logic only: zero custom authentication logic, zero token minting, zero login sessions.
"""

import time
import uuid
import secrets
import logging
from typing import Dict, List

from fastapi import APIRouter, Request, Form, status
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from core.config import settings
from core.context import set_current_tenant_id, clear_context
from db.supabase_client import db_service
from tools.foundation import check_login_status

logger = logging.getLogger("digital-invoice-web.onboarding")

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])
templates = Jinja2Templates(directory="templates")

# In-memory sliding window rate limiter: key -> list of timestamp floats
_rate_limits: Dict[str, List[float]] = {}
MAX_ATTEMPTS = 5
WINDOW_SECONDS = 300  # 5 minutes

def is_rate_limited(key: str) -> bool:
    """Check if key has exceeded MAX_ATTEMPTS in the last WINDOW_SECONDS."""
    now = time.time()
    timestamps = _rate_limits.get(key, [])
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

def mask_email(email: str) -> str:
    """Mask email for privacy, e.g. i***g@example.com."""
    if "@" not in email:
        return email
    local, domain = email.split("@", 1)
    if len(local) <= 2:
        masked_local = local[0] + "***"
    else:
        masked_local = local[0] + "***" + local[-1]
    return f"{masked_local}@{domain}"

def get_base_url(request: Request) -> str:
    """Compute base URL honoring reverse proxy forwarded headers."""
    base = str(request.base_url).rstrip("/")
    if request.headers.get("x-forwarded-proto") == "https" and base.startswith("http://"):
        base = "https://" + base[7:]
    return base


async def verify_tenant_credentials(tenant_id: str, email: str, password: str) -> bool:
    """
    Fetch stored decrypted credentials via db_service.get_decrypted_credentials(tenant_id).
    Compare email (case-insensitive) and password (exact) against submitted values.
    Return False if no stored record, or on any mismatch. Never raise on mismatch —
    only raise on actual DB/decryption errors. Never log submitted passwords.
    """
    try:
        creds = await db_service.get_decrypted_credentials(tenant_id)
        if not creds:
            return False
        stored_email = creds.get("email", "")
        stored_password = creds.get("password", "")
        if stored_email.strip().lower() != email.strip().lower():
            return False
        if stored_password != password:
            return False
        return True
    except Exception as e:
        logger.error(f"Error during credential verification for tenant {tenant_id}: {type(e).__name__}")
        raise


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def onboarding_form_page(request: Request):
    """
    Renders simple tenant credential onboarding form.
    No login step or token required to view this page.
    """
    return templates.TemplateResponse(
        request=request,
        name="onboarding/form.html",
        context={
            "form_data": {},
            "error": None
        }
    )


@router.post("", response_class=HTMLResponse)
@router.post("/", response_class=HTMLResponse)
async def onboarding_form_submit(
    request: Request,
    company_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...)
):
    """
    Handles submission of company portal credentials:
    1. Rate-limits by client IP.
    2. Generates / reuses internal tenant_id deterministically by email.
    3. Saves credentials using AES-256-GCM via db_service.save_tenant_credentials.
    4. Renders results page with MCP URL and per-LLM guides.
    Never logs submitted passwords anywhere.
    """
    ip = get_client_ip(request)
    if is_rate_limited(f"onboarding_post:{ip}"):
        return templates.TemplateResponse(
            request=request,
            name="onboarding/form.html",
            context={
                "form_data": {"company_name": company_name, "email": email},
                "error": "Too many submissions from this IP. Please wait a few minutes before trying again."
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS
        )

    clean_company = company_name.strip()
    clean_email = email.strip().lower()

    if not clean_company or not clean_email or not password:
        return templates.TemplateResponse(
            request=request,
            name="onboarding/form.html",
            context={
                "form_data": {"company_name": company_name, "email": email},
                "error": "All fields (Company Name, Email, Password) are required."
            },
            status_code=status.HTTP_400_BAD_REQUEST
        )

    # 1. Generate/reuse internal tenant_id for this company (lookup/deterministic by email)
    tenant_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, clean_email))
    url_token = secrets.token_urlsafe(24)

    # 2. Save credentials via existing db_service.save_tenant_credentials (no duplicate encryption logic)
    try:
        await db_service.save_tenant_credentials(
            tenant_id=tenant_id,
            company_name=clean_company,
            email=clean_email,
            password=password,
            key_version=settings.CURRENT_KEY_VERSION,
            url_token=url_token
        )
        logger.info(f"Onboarding: Successfully stored credentials for company '{clean_company}' (tenant_id={tenant_id})")
    except Exception as e:
        logger.error(f"Onboarding: Failed to save credentials for tenant {tenant_id}: {type(e).__name__}")
        return templates.TemplateResponse(
            request=request,
            name="onboarding/form.html",
            context={
                "form_data": {"company_name": company_name, "email": email},
                "error": f"Failed to save credentials: {str(e)}"
            },
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )

    # 3. Render results page
    base_url = get_base_url(request)
    mcp_server_url = f"{base_url}/mcp/{url_token}"
    sse_server_url = f"{base_url}/sse/{url_token}"
    mcp_api_key = settings.MCP_AUTH_TOKEN or settings.MCP_AUTH_AUDIENCE

    return templates.TemplateResponse(
        request=request,
        name="onboarding/results.html",
        context={
            "tenant_id": tenant_id,
            "company_name": clean_company,
            "masked_email": mask_email(clean_email),
            "base_url": base_url,
            "mcp_server_url": mcp_server_url,
            "sse_server_url": sse_server_url,
            "url_token": url_token,
            "mcp_api_key": mcp_api_key
        }
    )


@router.post("/test-connection")
async def onboarding_test_connection(
    request: Request,
    tenant_id: str = Form(...)
):
    """
    Executes existing check_login_status tool logic for this tenant_id to verify
    saved portal credentials work on digitalinvoicingsoftware.com.
    Unrelated to MCP auth.
    """
    ip = get_client_ip(request)
    if is_rate_limited(f"test_conn:{ip}"):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"success": False, "error": "Rate limit reached. Please wait before testing again."}
        )

    clean_tenant_id = tenant_id.strip()
    if not clean_tenant_id:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content={"success": False, "error": "Missing tenant_id for connection test."}
        )

    set_current_tenant_id(clean_tenant_id)
    try:
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
        logger.error(f"Onboarding connection test failed for tenant {clean_tenant_id}: {type(e).__name__}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "success": False,
                "is_logged_in": False,
                "error": f"Connection test error: {str(e)}"
            }
        )
    finally:
        clear_context()


@router.post("/regenerate-link")
async def onboarding_regenerate_link(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    """
    Regenerates MCP and SSE server URL token for a tenant after credential re-verification.
    Form fields: email, password (NOT tenant_id or url_token).
    """
    ip = get_client_ip(request)
    if is_rate_limited(f"regen_link:{ip}"):
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"success": False, "error": "Rate limit reached. Please wait before trying again."}
        )

    clean_email = email.strip().lower() if email else ""
    if not clean_email or not password:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"success": False, "error": "Invalid email or password"}
        )

    tenant_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, clean_email))

    try:
        is_valid = await verify_tenant_credentials(tenant_id, clean_email, password)
        if not is_valid:
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"success": False, "error": "Invalid email or password"}
            )

        new_token = await db_service.rotate_url_token(tenant_id)
        base_url = get_base_url(request)
        mcp_server_url = f"{base_url}/mcp/{new_token}"
        sse_server_url = f"{base_url}/sse/{new_token}"
        mcp_api_key = settings.MCP_AUTH_TOKEN or settings.MCP_AUTH_AUDIENCE

        logger.info(f"Onboarding: Successfully rotated url_token for tenant {tenant_id}")
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "success": True,
                "url_token": new_token,
                "mcp_server_url": mcp_server_url,
                "sse_server_url": sse_server_url,
                "mcp_api_key": mcp_api_key
            }
        )
    except Exception as e:
        logger.error(f"Failed to regenerate link: {type(e).__name__}")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"success": False, "error": f"Failed to regenerate link: {str(e)}"}
        )
