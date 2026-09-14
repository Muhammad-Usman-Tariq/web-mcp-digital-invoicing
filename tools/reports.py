import re
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
from core.config import settings
from browser.manager import browser_manager, ElementNotFoundError
from browser.selectors import PortalRoutes, ReportsLocators
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.reports")

def _format_calendar_date(date_str: str) -> str:
    """Format YYYY-MM-DD into calendar matching string, e.g. '7 September 2026'."""
    try:
        dt = datetime.strptime(date_str.strip(), "%Y-%m-%d")
        # Format as day Month Year, e.g. '14 September 2026'
        return f"{dt.day} {dt.strftime('%B')} {dt.year}"
    except Exception:
        return date_str.strip()

@mcp_tool_handler("filter_report_by_date_range")
async def filter_report_by_date_range(
    from_date: str,
    to_date: str,
    report_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Filters the reports page by date range on /dashboard/reports using the verified calendar picker.
    Clicks 'Select duration', selects start and end dates via accessible day buttons,
    clicks 'Load Reports', and returns parsed report rows.
    Format for from_date and to_date: YYYY-MM-DD.
    """
    report_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.REPORTS}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(report_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # 1. Open duration calendar picker
        duration_btn = page.get_by_role("button", name=ReportsLocators.SELECT_DURATION_BUTTON[1]).first
        if await duration_btn.is_visible(timeout=3000):
            await duration_btn.click()
            await page.wait_for_timeout(400)

            # Format search patterns
            from_pattern = _format_calendar_date(from_date)
            to_pattern = _format_calendar_date(to_date)

            # Click 'From' date button
            from_day_btn = page.get_by_role("button", name=re.compile(re.escape(from_pattern), re.I)).first
            if await from_day_btn.is_visible(timeout=2000):
                await from_day_btn.click()
                await page.wait_for_timeout(300)

            # Click 'To' date button
            to_day_btn = page.get_by_role("button", name=re.compile(re.escape(to_pattern), re.I)).first
            if await to_day_btn.is_visible(timeout=2000):
                await to_day_btn.click()
                await page.wait_for_timeout(300)

        # 2. Click 'Load Reports'
        load_btn = page.get_by_role("button", name=ReportsLocators.LOAD_REPORTS_BUTTON[1]).first
        if await load_btn.is_visible(timeout=2000):
            await load_btn.click()
        else:
            await page.keyboard.press("Enter")

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # 3. Extract report table rows
        table = page.locator("table").first
        if not await table.is_visible(timeout=4000):
            return {
                "from_date": from_date,
                "to_date": to_date,
                "rows_count": 0,
                "rows": [],
                "message": "Filter applied; no table records rendered."
            }

        headers: List[str] = []
        for th in await table.locator("thead th").all():
            headers.append((await th.inner_text()).strip())

        rows_data: List[Dict[str, Any]] = []
        for tr in await table.locator("tbody tr").all():
            cells = await tr.locator("td").all()
            if not cells:
                continue
            row_dict: Dict[str, Any] = {}
            for i, td in enumerate(cells):
                cell_text = (await td.inner_text()).strip()
                col_name = headers[i] if i < len(headers) and headers[i] else f"col_{i+1}"
                row_dict[col_name] = cell_text
            rows_data.append(row_dict)

        return {
            "from_date": from_date,
            "to_date": to_date,
            "report_type": report_type,
            "rows_count": len(rows_data),
            "rows": rows_data,
            "current_url": page.url
        }

@mcp_tool_handler("export_report_view")
async def export_report_view(export_format: str = "csv") -> Dict[str, Any]:
    """
    Triggers 'Export CSV' on /dashboard/reports using the confirmed Export CSV button.
    """
    report_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.REPORTS}"
    async with browser_manager.get_tenant_page() as page:
        if "/dashboard/reports" not in page.url:
            await page.goto(report_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        export_btn = page.get_by_role("button", name=ReportsLocators.EXPORT_CSV_BUTTON[1]).first
        if not await export_btn.is_visible(timeout=4000):
            raise ElementNotFoundError("Export CSV button not found on /dashboard/reports.")

        try:
            async with page.expect_download(timeout=10000) as download_info:
                await export_btn.click()
            download = await download_info.value
            filename = download.suggested_filename
            return {
                "status": "download_completed",
                "filename": filename,
                "export_format": export_format,
                "message": f"Successfully triggered and downloaded report file '{filename}'."
            }
        except Exception:
            return {
                "status": "export_initiated",
                "export_format": export_format,
                "current_url": page.url,
                "message": "Export CSV button clicked in UI."
            }
