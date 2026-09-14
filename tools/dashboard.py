import re
import logging
from typing import Dict, Any, List
from core.config import settings
from browser.manager import browser_manager
from browser.selectors import PortalRoutes, DashboardLocators
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.dashboard")

@mcp_tool_handler("get_dashboard_snapshot")
async def get_dashboard_snapshot() -> Dict[str, Any]:
    """
    Scrapes the live dashboard snapshot using verified accessible locators.
    Extracts stats ('Total Invoices', 'Total Draft Invoices', 'Total Validated Invoices',
    'Total Submitted Invoices'), alerts, and quick actions into structured JSON.
    """
    dashboard_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.DASHBOARD}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(dashboard_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        metrics: Dict[str, str] = {}
        quick_actions: List[Dict[str, str]] = []

        # 1. Scrape verified statistics
        stat_keys = [
            DashboardLocators.STAT_TOTAL_INVOICES,
            DashboardLocators.STAT_TOTAL_DRAFT_INVOICES,
            DashboardLocators.STAT_TOTAL_VALIDATED_INVOICES,
            DashboardLocators.STAT_TOTAL_SUBMITTED_INVOICES
        ]

        for stat_title in stat_keys:
            try:
                stat_loc = page.get_by_text(stat_title, exact=True).first
                if await stat_loc.is_visible(timeout=1500):
                    # Walk up to parent card element to extract associated count
                    parent_text = await stat_loc.locator("xpath=..").inner_text()
                    lines = [line.strip() for line in parent_text.split("\n") if line.strip()]
                    # Usually card format is [Title, Value] or [Value, Title]
                    val = "0"
                    for line in lines:
                        if line != stat_title and (line.replace(",", "").isdigit() or any(c.isdigit() for c in line)):
                            val = line
                            break
                    metrics[stat_title] = val
            except Exception as e:
                logger.debug(f"Could not extract stat '{stat_title}': {e}")

        # 2. Check for failed invoices alert button/badge
        try:
            failed_btn = page.get_by_role("button", name=re.compile(r"Failed", re.I)).first
            if await failed_btn.is_visible(timeout=1500):
                failed_text = await failed_btn.inner_text()
                metrics["Failed Invoices Alert"] = failed_text.strip()
        except Exception:
            pass

        # 3. Scrape verified quick action links
        confirmed_links = [
            ("Create / view invoices", DashboardLocators.QUICK_ACTION_CREATE_INVOICES[1]),
            ("Reports", DashboardLocators.QUICK_ACTION_REPORTS[1]),
            ("View failed invoices", DashboardLocators.FAILED_INVOICES_LINK[1])
        ]

        for label, name in confirmed_links:
            try:
                link_loc = page.get_by_role("link", name=name).first
                if await link_loc.is_visible(timeout=1000):
                    href = await link_loc.get_attribute("href")
                    quick_actions.append({"title": label, "url": href or ""})
            except Exception:
                continue

        title = await page.title()
        
        return {
            "page_title": title,
            "dashboard_url": page.url,
            "stats": metrics,
            "quick_actions": quick_actions
        }
