import logging
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.mcpserver import MCPServer
from mcp.server.sse import TransportSecuritySettings

from core.config import settings, validate_critical_settings
from core.context import set_current_auth_claims, clear_context
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
    """Navigate to a specific section of the portal (e.g. dashboard, invoices, failed_invoices, draft_invoices, reports, users, settings)."""
    return await navigate_to_section(section=section)

@mcp.tool()
async def tool_get_page_text(max_chars: int = 4000):
    """Inspect visible DOM text content of the current portal view for element discovery and diagnostics."""
    return await get_page_text(max_chars=max_chars)

@mcp.tool()
async def tool_take_screenshot(full_page: bool = False):
    """Capture a diagnostic PNG screenshot of the current portal view returned as a base64 data URL."""
    return await take_screenshot(full_page=full_page)

# --- High Priority Tools ---
@mcp.tool()
async def tool_get_dashboard_snapshot():
    """Scrape dashboard overview metrics, status counts, and quick-action links into structured JSON."""
    return await get_dashboard_snapshot()

@mcp.tool()
async def tool_get_failed_invoices_details(limit: int = 50):
    """Scrape the list of failed invoices with specific failure reasons directly from the UI."""
    return await get_failed_invoices_details(limit=limit)

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
async def tool_edit_draft_invoice_field(invoice_id: str, field_name: str, new_value: str):
    """Locate a draft invoice by ID, edit a specific field, and save changes."""
    return await edit_draft_invoice_field(invoice_id=invoice_id, field_name=field_name, new_value=new_value)

@mcp.tool()
async def tool_add_new_user(name: str, email: str, role: str = "User"):
    """Fill the Add User form on the portal user management screen and confirm creation."""
    return await add_new_user(name=name, email=email, role=role)

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
    yield
    logger.info("Closing Playwright browser pool on server shutdown...")
    await browser_manager.stop()

# 4. Initialize FastAPI Application
app = FastAPI(
    title="digital-invoice-web MCP Server",
    description="Multi-tenant Web-MCP server driving Digital Invoicing UI automation via Playwright.",
    version="1.0.0",
    lifespan=lifespan
)

# 5. Add Drop-in Central Auth Verification Middleware
app.add_middleware(
    McpAuthMiddleware,
    jwks_uri=settings.JWKS_URI,
    audience=settings.MCP_AUTH_AUDIENCE,
    revocations_uri=settings.REVOCATIONS_URI,
    exempt_paths=["/health", "/healthz", "/docs", "/openapi.json"]
)

# 6. Middleware to extract tenant claims into contextvars
@app.middleware("http")
async def extract_tenant_context(request: Request, call_next):
    try:
        auth_payload = getattr(request.state, "auth", None)
        if auth_payload and isinstance(auth_payload, dict):
            set_current_auth_claims(auth_payload)
        response = await call_next(request)
        return response
    finally:
        clear_context()

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

# 8. Mount MCP SSE and Streamable HTTP Transports
sec_settings = TransportSecuritySettings(enable_dns_rebinding_protection=False)
app.mount("/mcp", mcp.streamable_http_app())
app.mount("", mcp.sse_app(transport_security=sec_settings))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False
    )
