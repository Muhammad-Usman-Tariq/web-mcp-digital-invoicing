import asyncio
import sys
import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import Scope, Receive, Send
from starlette.routing import Mount
from mcp.server.mcpserver import MCPServer
from mcp.server.sse import SseServerTransport, TransportSecuritySettings

from core.config import settings, validate_critical_settings
from core.context import set_current_auth_claims, set_current_tenant_id, get_current_tenant_id, clear_context
from db.supabase_client import db_service
from sdk.python.mcp_auth_middleware import McpAuthMiddleware
from browser.manager import browser_manager

# Import all tools
from tools.foundation import (
    check_login_status,
    navigate_to_section,
    get_page_text,
    take_screenshot
)
from tools.dashboard import get_dashboard_snapshot
from tools.invoices import (
    list_draft_invoices,
    get_failed_invoices_details,
    bulk_validate_invoices,
    edit_draft_invoice_field,
    duplicate_invoice
)
from tools.reports import (
    filter_report_by_date_range,
    export_report_view
)
from tools.users import add_new_user
from tools.buyers import list_buyers

from routes.onboarding import router as onboarding_router

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("digital-invoice-web")

# 1. Initialize official MCP Server
mcp = MCPServer(
    name="digital-invoice-web",
    instructions="Automated web browser MCP server for Digital Invoicing Software UI actions."
)

# 2. Register tools with MCP Server
# --- Plumbing & Diagnostics ---
@mcp.tool()
async def tool_check_login_status():
    """Verify whether tenant currently has an active, authenticated browser session on the portal."""
    return await check_login_status()

@mcp.tool()
async def tool_navigate_to_section(section: str):
    """Test whether a specific section or path of the portal loads without error. NOTE: Each tool call operates in an isolated browser context, so navigating here does NOT leave the browser on this page for subsequent tool calls."""
    return await navigate_to_section(section=section)

@mcp.tool()
async def tool_get_page_text(path: str = "/dashboard", max_chars: int = 4000):
    """Navigate to the given portal path (e.g. '/buyers', '/dashboard/reports', '/invoices') and return visible DOM text content."""
    return await get_page_text(path=path, max_chars=max_chars)

@mcp.tool()
async def tool_take_screenshot(path: str = "/dashboard", full_page: bool = False):
    """Navigate to the given portal path and capture a diagnostic PNG screenshot returned as a base64 data URL."""
    return await take_screenshot(path=path, full_page=full_page)

@mcp.tool()
async def tool_list_buyers():
    """Return all buyers configured for this tenant with business name, address, registration type, NTN/CNIC, STRN, province, and active status."""
    return await list_buyers()

# --- High Priority Tools ---
@mcp.tool()
async def tool_get_dashboard_snapshot():
    """Scrape dashboard overview metrics, status counts, and quick-action links into structured JSON."""
    return await get_dashboard_snapshot()

@mcp.tool()
async def tool_get_failed_invoices_details(limit: int = 50, fetch_reasons: bool = False):
    """Scrape the list of failed invoices directly from the UI, optionally opening View Details for exact errors."""
    return await get_failed_invoices_details(limit=limit, fetch_reasons=fetch_reasons)

@mcp.tool()
async def tool_filter_report_by_date_range(from_date: str, to_date: str, report_type: Optional[str] = None):
    """Drive the report page date-picker filters (YYYY-MM-DD) and return parsed table rows in JSON."""
    return await filter_report_by_date_range(from_date=from_date, to_date=to_date, report_type=report_type)

# --- Medium Priority Tools ---
@mcp.tool()
async def tool_bulk_validate_invoices(invoice_ids: Optional[List[str]] = None, select_all: bool = False):
    """Select invoices via UI checkboxes and trigger bulk validation."""
    return await bulk_validate_invoices(invoice_ids=invoice_ids, select_all=select_all)

@mcp.tool()
async def tool_list_draft_invoices(limit: int = 50):
    """List draft invoices from the portal with real matchable fields (sr_number, date, buyer, amount, type, status). Call this before editing drafts."""
    return await list_draft_invoices(limit=limit)

@mcp.tool()
async def tool_edit_draft_invoice_field(
    buyer_name: str,
    date: str,
    field_name: str,
    new_value: str,
    amount: Optional[float] = None
):
    """Locate a draft invoice by buyer name and date (and optionally amount for disambiguation), edit a field in Invoice Studio, and save."""
    return await edit_draft_invoice_field(
        buyer_name=buyer_name,
        date=date,
        field_name=field_name,
        new_value=new_value,
        amount=amount
    )

@mcp.tool()
async def tool_add_new_user(
    full_name: str,
    email: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    company: Optional[str] = None,
    role: str = "Company Admin"
):
    """Fill the Add User modal on /users with full name, email, credentials, company, and role."""
    return await add_new_user(
        full_name=full_name,
        email=email,
        username=username,
        password=password,
        company=company,
        role=role
    )

# --- Low Priority Tools ---
@mcp.tool()
async def tool_duplicate_invoice(invoice_id: str):
    """Locate an invoice by ID in the UI and trigger the duplicate action."""
    return await duplicate_invoice(invoice_id=invoice_id)

@mcp.tool()
async def tool_export_report_view(export_format: str = "csv"):
    """Trigger the export action in the UI report view and return download status."""
    return await export_report_view(export_format=export_format)

# 3. Lifespan for FastAPI
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Explicit startup validation: fail fast with clear actionable error messages
    validation_errors = validate_critical_settings(settings)
    if validation_errors:
        for err in validation_errors:
            logger.critical(err)
        raise RuntimeError("\n".join(validation_errors))

    logger.info("Initializing Playwright browser pool on server startup...")
    await browser_manager.start()
    try:
        if getattr(mcp.session_manager, "_has_started", False) and mcp.session_manager._task_group is None:
            mcp.session_manager._has_started = False
        async with mcp.session_manager.run():
            yield
    finally:
        if getattr(mcp.session_manager, "_has_started", False):
            mcp.session_manager._has_started = False
        logger.info("Closing Playwright browser pool on server shutdown...")
        await browser_manager.stop()

# 4. Initialize FastAPI Application
app = FastAPI(
    title="digital-invoice-web MCP Server",
    description="Multi-tenant Web-MCP server driving Digital Invoicing UI automation via Playwright.",
    version="1.0.0",
    lifespan=lifespan
)

# 5. Middleware to extract tenant claims into contextvars (registered first so it runs after McpAuthMiddleware)
@app.middleware("http")
async def extract_tenant_context(request: Request, call_next):
    try:
        auth_payload = getattr(request.state, "auth", None)
        if auth_payload and isinstance(auth_payload, dict):
            set_current_auth_claims(auth_payload)

        # Resolve tenant by url_token for /mcp and /sse requests
        path = request.url.path
        if path == "/mcp" or path.startswith("/mcp/") or path == "/sse" or path.startswith("/sse/"):
            url_token = request.path_params.get("url_token")
            if not url_token:
                if path.startswith("/mcp/"):
                    token_candidate = path[len("/mcp/"):].split("/")[0].strip()
                    if token_candidate:
                        url_token = token_candidate
                elif path.startswith("/sse/"):
                    token_candidate = path[len("/sse/"):].split("/")[0].strip()
                    if token_candidate:
                        url_token = token_candidate

            if not url_token:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "unauthorized",
                        "error_description": "Missing authentication token. Provide Bearer or x-api-key header."
                    },
                    headers={"WWW-Authenticate": f'Bearer realm="{settings.MCP_AUTH_AUDIENCE}", error="unauthorized"'}
                )

            resolved_tenant_id = await db_service.get_tenant_id_by_url_token(url_token)
            if not resolved_tenant_id:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": "unauthorized",
                        "error_description": "Missing authentication token. Provide Bearer or x-api-key header."
                    },
                    headers={"WWW-Authenticate": f'Bearer realm="{settings.MCP_AUTH_AUDIENCE}", error="unauthorized"'}
                )
            set_current_tenant_id(resolved_tenant_id)

        response = await call_next(request)
        return response
    finally:
        clear_context()

# 6. Add Drop-in Central Auth Verification Middleware (registered second so it runs as the outer layer)
app.add_middleware(
    McpAuthMiddleware,
    jwks_uri=settings.JWKS_URI,
    audience=settings.MCP_AUTH_AUDIENCE,
    revocations_uri=settings.REVOCATIONS_URI,
    exempt_paths=["/health", "/healthz", "/docs", "/openapi.json", "/onboarding"]
)

# 7. Unauthenticated Health Check Endpoint for VPS / Coolify Monitoring
@app.get("/health", tags=["Monitoring"])
@app.get("/healthz", tags=["Monitoring"])
async def health_check():
    return {
        "status": "ok",
        "service": "digital-invoice-web",
        "version": "1.0.0",
        "audience": settings.MCP_AUTH_AUDIENCE
    }

# 8. Include Onboarding Web UI Router
app.include_router(onboarding_router)

# In-memory mapping: session_id (hex str) -> tenant_id
# NOTE: This in-memory mapping is suitable for single-process deployments.
# Before moving to multi-process / multi-worker deployments, migrate this to a shared cache like Redis.
_sse_session_tenants: Dict[str, str] = {}

class TenantAwareSseServerTransport(SseServerTransport):
    """
    SseServerTransport subclass that intercepts session_id generated inside connect_sse
    and records session_id -> tenant_id in _sse_session_tenants for tenant-isolated message routing.
    Cleans up session_id on connection disconnect.
    Uses an asyncio.Lock around the connect handshake and session diffing to prevent
    concurrent interleaving from misattributing or conflating sessions across tenants.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._connect_lock = asyncio.Lock()

    @asynccontextmanager
    async def connect_sse(self, scope: Scope, receive: Receive, send: Send):
        async with self._connect_lock:
            existing_keys = set(self._read_stream_writers.keys())
            cm = super().connect_sse(scope, receive, send)
            streams = await cm.__aenter__()
            new_keys = set(self._read_stream_writers.keys()) - existing_keys
            session_id = next(iter(new_keys)) if len(new_keys) == 1 else None
            tenant_id = get_current_tenant_id()
            if session_id and tenant_id:
                _sse_session_tenants[session_id.hex] = tenant_id
                logger.debug(f"Mapped SSE session {session_id.hex} to tenant {tenant_id}")
            elif not session_id:
                logger.error(
                    "SSE session_id capture ambiguous or failed "
                    f"(new_keys={len(new_keys)}) - refusing to guess tenant mapping"
                )
        # lock released here — actual streaming happens outside the lock
        try:
            yield streams
        except BaseException:
            exc_info = sys.exc_info()
            await cm.__aexit__(*exc_info)
            raise
        else:
            await cm.__aexit__(None, None, None)
        finally:
            if session_id:
                _sse_session_tenants.pop(session_id.hex, None)
                logger.debug(f"Cleaned up SSE session {session_id.hex}")

# Patch SseServerTransport in mcpserver module before sse_app is instantiated
from mcp.server.mcpserver import server as mcpserver_module
mcpserver_module.SseServerTransport = TenantAwareSseServerTransport

# 9. Register MCP Streamable HTTP and SSE Transports
sec_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
streamable_app = mcp.streamable_http_app(
    transport_security=sec_settings,
    streamable_http_path="/mcp/{url_token}"
)
sse_app = mcp.sse_app(
    transport_security=sec_settings,
    sse_path="/sse/{url_token}"
)

# Append streamable HTTP routes
for route in streamable_app.routes:
    app.routes.append(route)

# Append only the parameterized SSE handshake GET route from sse_app
sse_get_route = next(r for r in sse_app.routes if getattr(r, "path", None) == "/sse/{url_token}")
app.routes.append(sse_get_route)

# Extract the SseServerTransport instance created by sse_app
raw_mount_route = next(r for r in sse_app.routes if getattr(r, "path", None) in ("/messages", "/messages/"))
sse_transport = getattr(raw_mount_route.app, "__self__", None)

async def messages_app(scope: Scope, receive: Receive, send: Send):
    """
    Tenant-resolved POST handler for SSE messages.
    Validates session_id against _sse_session_tenants, sets current_tenant_id,
    and delegates to sse_transport.handle_post_message.
    """
    if scope["type"] != "http":
        return
    request = Request(scope, receive)
    session_id = request.query_params.get("session_id")
    if not session_id or session_id not in _sse_session_tenants:
        response = JSONResponse(
            status_code=401,
            content={
                "error": "unauthorized",
                "error_description": "Missing authentication token. Provide Bearer or x-api-key header."
            },
            headers={"WWW-Authenticate": f'Bearer realm="{settings.MCP_AUTH_AUDIENCE}", error="unauthorized"'}
        )
        return await response(scope, receive, send)

    tenant_id = _sse_session_tenants[session_id]
    set_current_tenant_id(tenant_id)
    try:
        await sse_transport.handle_post_message(scope, receive, send)
    finally:
        clear_context()

# Mount custom tenant-resolved /messages route
app.routes.append(Mount("/messages", app=messages_app))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False
    )
