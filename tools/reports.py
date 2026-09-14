import logging
from typing import Dict, Any, List, Optional
from core.config import settings
from browser.manager import browser_manager, ElementNotFoundError
from browser.selectors import PortalRoutes, ReportSelectors
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.reports")

@mcp_tool_handler("filter_report_by_date_range")
async def filter_report_by_date_range(
    from_date: str,
    to_date: str,
    report_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Drives the report page date-picker inputs (from_date and to_date), applies the filter,
    and returns parsed table rows in structured JSON.
    Date format: YYYY-MM-DD
    """
    report_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.REPORTS}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(report_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # 1. Optionally select report type if dropdown present
        if report_type:
            type_select = page.locator("select[name='report_type'], #report-type").first
            if await type_select.is_visible(timeout=2000):
                await type_select.select_option(label=report_type)

        # 2. Set 'From' Date
        from_sel = await browser_manager.find_element(page, ReportSelectors.DATE_FROM_INPUT, timeout_ms=3000)
        if not from_sel:
            raise ElementNotFoundError(f"From Date input not found. Tested: {ReportSelectors.DATE_FROM_INPUT}")
        await page.fill(from_sel, from_date)

        # 3. Set 'To' Date
        to_sel = await browser_manager.find_element(page, ReportSelectors.DATE_TO_INPUT, timeout_ms=3000)
        if not to_sel:
            raise ElementNotFoundError(f"To Date input not found. Tested: {ReportSelectors.DATE_TO_INPUT}")
        await page.fill(to_sel, to_date)

        # 4. Click Apply/Filter button
        apply_sel = await browser_manager.find_element(page, ReportSelectors.APPLY_FILTER_BUTTON, timeout_ms=3000)
        if apply_sel:
            await page.click(apply_sel)
        else:
            await page.keyboard.press("Enter")

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # 5. Extract results table
        table_sel = await browser_manager.find_element(page, ReportSelectors.REPORT_TABLE, timeout_ms=5000)
        if not table_sel:
            return {
                "from_date": from_date,
                "to_date": to_date,
                "rows_count": 0,
                "rows": [],
                "message": "Filter applied; no table records rendered."
            }

        headers: List[str] = []
        for th in await page.locator(f"{table_sel} th").all():
            headers.append((await th.inner_text()).strip().lower())

        rows_data: List[Dict[str, Any]] = []
        for tr in await page.locator(f"{table_sel} tbody tr").all():
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
    Triggers the report view export action in the UI and captures the download or export URL.
    """
    report_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.REPORTS}"
    async with browser_manager.get_tenant_page() as page:
        if PortalRoutes.REPORTS not in page.url:
            await page.goto(report_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # Click export button
        export_btn = await browser_manager.find_element(page, ReportSelectors.EXPORT_BUTTON, timeout_ms=4000)
        if not export_btn:
            raise ElementNotFoundError(f"Export button not found. Candidates: {ReportSelectors.EXPORT_BUTTON}")

        # Listen for download event or direct navigation
        try:
            async with page.expect_download(timeout=10000) as download_info:
                await page.click(export_btn)
            download = await download_info.value
            filename = download.suggested_filename
            return {
                "status": "download_completed",
                "filename": filename,
                "export_format": export_format,
                "message": f"Successfully triggered and downloaded report file '{filename}'."
            }
        except Exception:
            # Fallback if export triggered a modal or link
            return {
                "status": "export_initiated",
                "export_format": export_format,
                "current_url": page.url,
                "message": "Export action clicked in UI."
            }
