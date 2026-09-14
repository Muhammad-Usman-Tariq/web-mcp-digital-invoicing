import logging
from typing import Dict, Any, List, Optional
from core.config import settings
from browser.manager import browser_manager, ElementNotFoundError
from browser.selectors import PortalRoutes, InvoiceSelectors
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.invoices")

@mcp_tool_handler("get_failed_invoices_details")
async def get_failed_invoices_details(limit: int = 50) -> Dict[str, Any]:
    """
    Extracts a structured list of failed invoices with specific failure reasons directly from the UI.
    Navigates to the failed invoices section and parses table columns into JSON.
    """
    failed_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.FAILED_INVOICES}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(failed_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        table_sel = await browser_manager.find_element(page, InvoiceSelectors.TABLE, timeout_ms=5000)
        if not table_sel:
            # Check if there is an empty state notice
            page_text = (await page.inner_text("body")).lower()
            if "no failed" in page_text or "no records" in page_text or "0 invoices" in page_text:
                return {
                    "total_failed": 0,
                    "invoices": [],
                    "message": "No failed invoices found on portal."
                }
            raise ElementNotFoundError(f"Could not locate invoice table on {page.url}")

        # Parse table headers
        headers: List[str] = []
        header_els = await page.locator(f"{table_sel} th").all()
        for h in header_els:
            headers.append((await h.inner_text()).strip().lower())

        # Parse rows
        row_els = await page.locator(f"{table_sel} tbody tr").all()
        failed_invoices: List[Dict[str, Any]] = []

        for row in row_els[:limit]:
            cols = await row.locator("td").all()
            if not cols:
                continue
            row_data: Dict[str, Any] = {}
            for i, col in enumerate(cols):
                col_text = (await col.inner_text()).strip()
                col_key = headers[i] if i < len(headers) and headers[i] else f"col_{i+1}"
                row_data[col_key] = col_text

            failed_invoices.append(row_data)

        return {
            "total_failed": len(failed_invoices),
            "invoices": failed_invoices,
            "current_url": page.url
        }

@mcp_tool_handler("bulk_validate_invoices")
async def bulk_validate_invoices(
    invoice_ids: Optional[List[str]] = None,
    select_all: bool = False
) -> Dict[str, Any]:
    """
    Selects invoices via checkboxes in the UI and triggers the bulk validate action.
    Can validate all visible invoices or a specific list of invoice IDs.
    """
    invoices_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.INVOICES}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(invoices_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        selected_count = 0
        if select_all:
            # Click master checkbox if available
            master_checkbox = page.locator("thead input[type='checkbox']").first
            if await master_checkbox.is_visible(timeout=2000):
                await master_checkbox.check()
                selected_count = await page.locator("tbody input[type='checkbox']:checked").count()
            else:
                # Check each row checkbox
                boxes = await page.locator("tbody input[type='checkbox']").all()
                for box in boxes:
                    await box.check()
                    selected_count += 1
        elif invoice_ids:
            # Check rows matching specified IDs
            for inv_id in invoice_ids:
                row_locator = page.locator(f"tr:has-text('{inv_id}')")
                if await row_locator.count() > 0:
                    checkbox = row_locator.locator("input[type='checkbox']").first
                    if await checkbox.is_visible(timeout=1000):
                        await checkbox.check()
                        selected_count += 1
        else:
            raise ValueError("Must specify either invoice_ids list or select_all=True.")

        if selected_count == 0:
            return {
                "success": False,
                "validated_count": 0,
                "message": "No matching invoices found to select for validation."
            }

        # Click bulk validate button
        btn_sel = await browser_manager.find_element(page, InvoiceSelectors.BULK_VALIDATE_BUTTON, timeout_ms=3000)
        if not btn_sel:
            raise ElementNotFoundError("Bulk Validate button not found on invoices page.")

        await page.click(btn_sel)
        # Handle confirmation dialog if triggered
        try:
            confirm_btn = page.locator("button:has-text('Confirm'), button:has-text('Yes'), .swal2-confirm").first
            if await confirm_btn.is_visible(timeout=2000):
                await confirm_btn.click()
        except Exception:
            pass

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        return {
            "selected_count": selected_count,
            "status": "validation_triggered",
            "message": f"Bulk validation triggered for {selected_count} invoices.",
            "current_url": page.url
        }

@mcp_tool_handler("edit_draft_invoice_field")
async def edit_draft_invoice_field(
    invoice_id: str,
    field_name: str,
    new_value: str
) -> Dict[str, Any]:
    """
    Locates a draft invoice by ID, navigates to its edit form, updates the specified field, and saves.
    """
    draft_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.DRAFT_INVOICES}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(draft_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # Locate row with invoice_id
        row = page.locator(f"tr:has-text('{invoice_id}')").first
        if not await row.is_visible(timeout=4000):
            raise ElementNotFoundError(f"Draft invoice '{invoice_id}' not found in draft list.")

        # Click Edit action
        edit_btn = row.locator("button:has-text('Edit'), a:has-text('Edit'), [title='Edit']").first
        if await edit_btn.is_visible(timeout=2000):
            await edit_btn.click()
        else:
            # Try clicking the row link directly
            link = row.locator("a").first
            await link.click()

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # Target input field by name, id, or placeholder
        field_candidates = [
            f"input[name='{field_name}']",
            f"textarea[name='{field_name}']",
            f"#{field_name}",
            f"input[placeholder*='{field_name}' i]",
            f"input[data-field='{field_name}']"
        ]
        matched_sel = await browser_manager.find_element(page, field_candidates, timeout_ms=5000)
        if not matched_sel:
            raise ElementNotFoundError(
                f"Field '{field_name}' not found on draft invoice edit form. Tested candidates: {field_candidates}"
            )

        await page.fill(matched_sel, new_value)

        # Click save button
        save_sel = await browser_manager.find_element(page, InvoiceSelectors.SAVE_INVOICE_BUTTON, timeout_ms=3000)
        if save_sel:
            await page.click(save_sel)
        else:
            await page.keyboard.press("Enter")

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        return {
            "invoice_id": invoice_id,
            "field_name": field_name,
            "new_value": new_value,
            "status": "saved",
            "current_url": page.url
        }

@mcp_tool_handler("duplicate_invoice")
async def duplicate_invoice(invoice_id: str) -> Dict[str, Any]:
    """
    Locates an invoice by ID in the invoices list and triggers the UI duplicate action.
    """
    invoices_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.INVOICES}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(invoices_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        row = page.locator(f"tr:has-text('{invoice_id}')").first
        if not await row.is_visible(timeout=4000):
            raise ElementNotFoundError(f"Invoice '{invoice_id}' not found in invoices list.")

        # Click Duplicate action
        dup_btn = row.locator("button:has-text('Duplicate'), a:has-text('Duplicate'), [title='Duplicate'], [aria-label='Duplicate']").first
        if not await dup_btn.is_visible(timeout=2000):
            # Try action menu dropdown
            menu_btn = row.locator(".dropdown-toggle, button[aria-haspopup='true'], .actions-btn").first
            if await menu_btn.is_visible(timeout=1000):
                await menu_btn.click()
                dup_btn = page.locator("button:has-text('Duplicate'), a:has-text('Duplicate')").first

        if not await dup_btn.is_visible(timeout=2000):
            raise ElementNotFoundError(f"Duplicate action not found for invoice '{invoice_id}'.")

        await dup_btn.click()
        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        return {
            "source_invoice_id": invoice_id,
            "status": "duplicated",
            "new_page_url": page.url,
            "page_title": await page.title()
        }
