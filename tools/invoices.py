import re
import logging
from typing import Dict, Any, List, Optional
from core.config import settings
from browser.manager import browser_manager, ElementNotFoundError
from browser.selectors import (
    PortalRoutes,
    InvoiceListLocators,
    InvoiceStudioLocators
)
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.invoices")

@mcp_tool_handler("get_failed_invoices_details")
async def get_failed_invoices_details(limit: int = 50, fetch_reasons: bool = False) -> Dict[str, Any]:
    """
    Extracts structured list of failed invoices directly from the UI.
    Navigates to /invoices?status=failed,validation_failed and parses the verified table columns:
    [Sr #, Invoice ID, Date, Type, Buyer, Invoice Amount, Status, Actions].
    If fetch_reasons=True, opens 'View Details' on each row to extract specific failure error messages.
    """
    failed_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.INVOICES_FAILED}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(failed_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # Look for table
        table = page.locator("table").first
        if not await table.is_visible(timeout=5000):
            page_text = (await page.inner_text("body")).lower()
            if "no invoice" in page_text or "no records" in page_text or "0 invoices" in page_text:
                return {
                    "total_failed": 0,
                    "invoices": [],
                    "message": "No failed invoices found on portal."
                }
            raise ElementNotFoundError(f"Invoices table not found on {page.url}")

        headers = InvoiceListLocators.TABLE_COLUMNS
        row_els = await page.locator("table tbody tr").all()
        failed_invoices: List[Dict[str, Any]] = []

        for row in row_els[:limit]:
            cols = await row.locator("td").all()
            if not cols or len(cols) < 2:
                continue
            row_data: Dict[str, Any] = {}
            for i, col in enumerate(cols):
                col_text = (await col.inner_text()).strip()
                col_key = headers[i] if i < len(headers) else f"col_{i+1}"
                if col_key != "Actions":
                    row_data[col_key] = col_text

            # If requested, inspect specific failure reason via View Details
            if fetch_reasons:
                try:
                    actions_btn = row.get_by_role("button", name=InvoiceListLocators.ROW_ACTIONS_BUTTON_TEXT).first
                    if await actions_btn.is_visible(timeout=1500):
                        await actions_btn.click()
                        await page.wait_for_timeout(200)
                        view_opt = page.get_by_text(InvoiceListLocators.ACTION_MENU_VIEW_DETAILS, exact=True).first
                        if await view_opt.is_visible(timeout=1500):
                            await view_opt.click()
                            await page.wait_for_timeout(400)
                            # Look for dialog/drawer error text
                            dialog = page.locator("[role='dialog'], [role='alert'], .modal").first
                            if await dialog.is_visible(timeout=2000):
                                dialog_text = await dialog.inner_text()
                                row_data["failure_reason"] = dialog_text.strip()
                            await page.keyboard.press("Escape")
                except Exception as e:
                    logger.debug(f"Could not fetch details for row: {e}")

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
    Validates multiple invoices sequentially using the verified per-row Actions -> Validate menu flow.
    (Note: The live UI has no bulk-checkboxes; validation is triggered per-row in a reliable loop).
    """
    invoices_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.INVOICES}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(invoices_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        rows = await page.locator("table tbody tr").all()
        if not rows:
            return {
                "validated_count": 0,
                "invoices_validated": [],
                "message": "No invoices present in table."
            }

        validated_invoices: List[str] = []
        errors: List[Dict[str, str]] = []

        # Determine target rows
        targets: List[Any] = []
        if select_all:
            targets = rows
        elif invoice_ids:
            for inv_id in invoice_ids:
                row_match = page.locator(f"table tbody tr:has-text('{inv_id}')").first
                if await row_match.is_visible(timeout=1500):
                    targets.append(row_match)
                else:
                    errors.append({"invoice_id": inv_id, "error": "Invoice row not found on page"})
        else:
            raise ValueError("Must specify either invoice_ids list or select_all=True.")

        for row in targets:
            try:
                row_text = await row.inner_text()
                # Find Actions button in this specific row
                actions_btn = row.get_by_role("button", name=InvoiceListLocators.ROW_ACTIONS_BUTTON_TEXT).first
                if not await actions_btn.is_visible(timeout=2000):
                    actions_btn = row.locator("button:has-text('Actions')").first

                if not await actions_btn.is_visible(timeout=2000):
                    continue

                await actions_btn.click()
                await page.wait_for_timeout(300)

                # Click Validate from the dropdown menu
                validate_opt = page.get_by_text(InvoiceListLocators.ACTION_MENU_VALIDATE, exact=True).first
                if await validate_opt.is_visible(timeout=2000):
                    await validate_opt.click()
                    # Handle any confirmation modal
                    confirm_btn = page.locator("button:has-text('Confirm'), button:has-text('Yes'), .swal2-confirm").first
                    if await confirm_btn.is_visible(timeout=1000):
                        await confirm_btn.click()
                    
                    await page.wait_for_timeout(500)
                    validated_invoices.append(row_text.split()[1] if len(row_text.split()) > 1 else "invoice")
                else:
                    # Close menu if validate option not available
                    await page.keyboard.press("Escape")
            except Exception as e:
                logger.warning(f"Error validating row: {e}")
                errors.append({"error": str(e)})

        return {
            "validated_count": len(validated_invoices),
            "invoices_validated": validated_invoices,
            "errors": errors,
            "message": f"Successfully triggered validation on {len(validated_invoices)} invoices."
        }

@mcp_tool_handler("edit_draft_invoice_field")
async def edit_draft_invoice_field(
    invoice_id: str,
    field_name: str,
    new_value: str
) -> Dict[str, Any]:
    """
    Locates a draft invoice by ID, opens Invoice Studio via Actions -> Edit Invoice,
    updates the specified field, and saves changes.
    """
    drafts_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.INVOICES_DRAFT}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(drafts_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # Locate row with invoice_id
        row = page.locator(f"table tbody tr:has-text('{invoice_id}')").first
        if not await row.is_visible(timeout=4000):
            raise ElementNotFoundError(f"Invoice '{invoice_id}' not found in draft list.")

        # Click Actions button
        actions_btn = row.get_by_role("button", name=InvoiceListLocators.ROW_ACTIONS_BUTTON_TEXT).first
        if not await actions_btn.is_visible(timeout=2000):
            actions_btn = row.locator("button:has-text('Actions')").first
        await actions_btn.click()
        await page.wait_for_timeout(300)

        # Click Edit Invoice
        edit_opt = page.get_by_text(InvoiceListLocators.ACTION_MENU_EDIT_INVOICE, exact=True).first
        if not await edit_opt.is_visible(timeout=2000):
            raise ElementNotFoundError(f"Edit Invoice action not available for invoice '{invoice_id}'.")
        await edit_opt.click()

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # Locate target field using verified placeholder / input mapping
        field_lower = field_name.lower().strip()
        input_target = None

        if "ref" in field_lower:
            input_target = page.get_by_placeholder(InvoiceStudioLocators.REFERENCE_NO_INPUT_PLACEHOLDER).first
        elif "po" in field_lower:
            input_target = page.get_by_placeholder(InvoiceStudioLocators.PO_NUMBER_INPUT_PLACEHOLDER).first
        elif "miv" in field_lower:
            input_target = page.get_by_placeholder(re.compile(r"MIV", re.I)).first
        elif "vendor" in field_lower:
            input_target = page.get_by_placeholder(re.compile(r"vendor", re.I)).first
        elif "dc" in field_lower or "challan" in field_lower or "delivery" in field_lower:
            input_target = page.get_by_placeholder(re.compile(r"(delivery|challan|DC)", re.I)).first
        elif "date" in field_lower:
            input_target = page.locator(InvoiceStudioLocators.INVOICE_DATE_INPUT).first
        else:
            # Try by placeholder substring or name attribute
            input_target = page.get_by_placeholder(re.compile(field_name, re.I)).first
            if not await input_target.is_visible(timeout=1000):
                input_target = page.locator(f"input[name='{field_name}']").first

        if not input_target or not await input_target.is_visible(timeout=3000):
            raise ElementNotFoundError(
                f"Field '{field_name}' not found in Invoice Studio. Known fields: reference, po, miv, vendor, dc/challan, date."
            )

        await input_target.fill(new_value)

        # Click Save button
        save_btn = page.get_by_role("button", name=InvoiceStudioLocators.SAVE_BUTTON[1]).first
        if await save_btn.is_visible(timeout=2000):
            await save_btn.click()
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
    Locates an invoice by ID in the UI and checks for duplicate capabilities.
    NOTE: Live inspection confirmed the Actions menu ONLY supports [View Details, Edit Invoice,
    Delete Invoice, Validate]. No 'Duplicate' feature exists in the portal UI.
    """
    # Live inspection on 2026-09-14 confirmed no Duplicate action exists in the portal UI.
    raise NotImplementedError(
        f"Duplicate action is not supported in the portal UI for invoice '{invoice_id}'. "
        "The verified Actions menu only contains: View Details, Edit Invoice, Delete Invoice, and Validate."
    )
