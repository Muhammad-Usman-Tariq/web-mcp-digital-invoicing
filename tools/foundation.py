import base64
from typing import Dict, Any, Optional
from core.config import settings
from browser.manager import browser_manager
from browser.selectors import PortalRoutes, LoginLocators
from .base import mcp_tool_handler

@mcp_tool_handler("check_login_status")
async def check_login_status() -> Dict[str, Any]:
    """
    Diagnostic tool to verify whether the calling tenant's browser session is active and authenticated.
    Attempts to access the dashboard and confirms absence of login redirect.
    """
    async with browser_manager.get_tenant_page() as page:
        current_url = page.url
        title = await page.title()
        is_logged_in = "/login" not in current_url.lower()
        
        return {
            "is_logged_in": is_logged_in,
            "current_url": current_url,
            "page_title": title,
            "is_on_dashboard": "/dashboard" in current_url.lower()
        }

@mcp_tool_handler("navigate_to_section")
async def navigate_to_section(section: str) -> Dict[str, Any]:
    """
    Navigate directly to a known section of the portal.
    Supported sections: dashboard, invoices, failed_invoices, draft_invoices, reports,
    buyers, users, roles, settings, scenarios_testing, docs.
    """
    section_map = {
        "dashboard": PortalRoutes.DASHBOARD,
        "invoices": PortalRoutes.INVOICES,
        "failed_invoices": PortalRoutes.INVOICES_FAILED,
        "draft_invoices": PortalRoutes.INVOICES_DRAFT,
        "reports": PortalRoutes.REPORTS,
        "buyers": PortalRoutes.BUYERS,
        "users": PortalRoutes.USERS,
        "roles": PortalRoutes.ROLES,
        "settings": PortalRoutes.SETTINGS,
        "scenarios_testing": PortalRoutes.SCENARIOS_TESTING,
        "docs": PortalRoutes.DOCS
    }
    
    target_path = section_map.get(section.lower().strip())
    if not target_path:
        # If user passed custom relative path, support it safely
        if section.startswith("/"):
            target_path = section
        else:
            supported = list(section_map.keys())
            raise ValueError(f"Unknown section '{section}'. Supported sections: {supported}")

    target_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{target_path}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(target_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
        return {
            "section": section,
            "final_url": page.url,
            "page_title": await page.title()
        }

@mcp_tool_handler("get_page_text")
async def get_page_text(max_chars: int = 4000) -> Dict[str, Any]:
    """
    Diagnostic tool to inspect visible DOM text of current view.
    Vital for inspecting page structure, headings, and tables during setup without guesswork.
    """
    async with browser_manager.get_tenant_page() as page:
        # Extract text from main container or body
        body_handle = await page.query_selector("main, #app, #root, body")
        if body_handle:
            text = await body_handle.inner_text()
        else:
            text = await page.inner_text("body")
        
        trimmed = text.strip()[:max_chars]
        return {
            "current_url": page.url,
            "page_title": await page.title(),
            "character_count": len(trimmed),
            "text_sample": trimmed
        }

@mcp_tool_handler("take_screenshot")
async def take_screenshot(full_page: bool = False) -> Dict[str, Any]:
    """
    Diagnostic tool capturing a screenshot of the current portal view as a base64 PNG data URL.
    Used for verifying UI layouts, inspecting elements, or troubleshooting unexpected dialogs.
    """
    async with browser_manager.get_tenant_page() as page:
        screenshot_bytes = await page.screenshot(full_page=full_page)
        b64_img = base64.b64encode(screenshot_bytes).decode("ascii")
        return {
            "current_url": page.url,
            "page_title": await page.title(),
            "mime_type": "image/png",
            "data_url": f"data:image/png;base64,{b64_img}",
            "size_bytes": len(screenshot_bytes)
        }
