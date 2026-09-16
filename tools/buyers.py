import logging
from typing import Dict, Any, List
from core.config import settings
from browser.manager import browser_manager, close_blocking_overlays
from browser.selectors import PortalRoutes
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.buyers")

@mcp_tool_handler("list_buyers")
async def list_buyers() -> Dict[str, Any]:
    """
    Return all buyers configured for this tenant, with business name, address,
    registration type, NTN/CNIC, STRN, province, and active status.
    """
    buyers_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.BUYERS}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(buyers_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
        await close_blocking_overlays(page)

        table = page.locator("table").first
        if not await table.is_visible(timeout=5000):
            return {
                "total_buyers": 0,
                "buyers": [],
                "message": "No buyers table found on page."
            }

        rows = await page.locator("table tbody tr").all()
        buyers: List[Dict[str, Any]] = []

        for row in rows:
            cols = [await td.inner_text() for td in await row.locator("td").all()]
            if len(cols) >= 7:
                buyers.append({
                    "business_name": cols[0].strip(),
                    "address": cols[1].strip(),
                    "registration_type": cols[2].strip(),
                    "ntn_cnic": cols[3].strip(),
                    "strn": cols[4].strip(),
                    "province": cols[5].strip(),
                    "status": cols[6].strip()
                })

        return {
            "total_buyers": len(buyers),
            "buyers": buyers,
            "current_url": page.url
        }
