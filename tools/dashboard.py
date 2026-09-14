import logging
from typing import Dict, Any, List
from core.config import settings
from browser.manager import browser_manager
from browser.selectors import PortalRoutes, DashboardSelectors
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.dashboard")

@mcp_tool_handler("get_dashboard_snapshot")
async def get_dashboard_snapshot() -> Dict[str, Any]:
    """
    Scrapes the live dashboard snapshot including high-level metric cards,
    quick-action links, and recent invoice activity into structured JSON.
    """
    dashboard_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.DASHBOARD}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(dashboard_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        metrics: List[Dict[str, str]] = []
        quick_links: List[Dict[str, str]] = []

        # 1. Scrape metric cards
        card_sel = await browser_manager.find_element(page, DashboardSelectors.METRIC_CARDS, timeout_ms=3000)
        if card_sel:
            cards = await page.locator(card_sel).all()
            for card in cards:
                try:
                    text = (await card.inner_text()).strip()
                    lines = [line.strip() for line in text.split("\n") if line.strip()]
                    if len(lines) >= 2:
                        label, val = lines[0], lines[1]
                    elif len(lines) == 1:
                        label, val = "Metric", lines[0]
                    else:
                        continue
                    metrics.append({"label": label, "value": val})
                except Exception:
                    continue

        # 2. Scrape quick links
        link_sel = await browser_manager.find_element(page, DashboardSelectors.QUICK_LINKS, timeout_ms=2000)
        if link_sel:
            links = await page.locator(link_sel).all()
            for link in links[:10]:
                try:
                    href = await link.get_attribute("href")
                    text = (await link.inner_text()).strip()
                    if href and text:
                        quick_links.append({"title": text, "url": href})
                except Exception:
                    continue

        # 3. Overall title and text snippet
        title = await page.title()
        
        return {
            "page_title": title,
            "dashboard_url": page.url,
            "metrics_count": len(metrics),
            "metrics": metrics,
            "quick_links": quick_links
        }
