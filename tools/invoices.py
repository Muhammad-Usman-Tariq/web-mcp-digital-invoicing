import re
import logging
from typing import Dict, Any, List, Optional
from core.config import settings
from browser.manager import browser_manager, ElementNotFoundError, close_blocking_overlays
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
        await close_blocking_overlays(page)

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
        await close_blocking_overlays(page)

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

from datetime import datetime

def _date_matches(input_date: str, table_date: str) -> bool:
    """Check if input_date matches the table date string across common formats."""
    inp = input_date.strip().lower()
    tbl = table_date.strip().lower()
    if inp in tbl or tbl in inp:
        return True

    # Try parsing common date formats
    date_formats_input = [
        "%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y", "%d/%m/%Y", "%m/%d/%Y",
        "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y"
    ]
    date_formats_table = [
        "%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"
    ]

    parsed_inp = None
    for fmt in date_formats_input:
        try:
            parsed_inp = datetime.strptime(input_date.strip(), fmt).date()
            break
        except ValueError:
            pass

    parsed_tbl = None
    for fmt in date_formats_table:
        try:
            parsed_tbl = datetime.strptime(table_date.strip(), fmt).date()
            break
        except ValueError:
            pass

    if parsed_inp and parsed_tbl:
        return parsed_inp == parsed_tbl

    return False

def _amount_matches(input_amount: Optional[float], table_amount_str: str) -> bool:
    """Check if input amount matches table amount within 0.01 tolerance."""
    if input_amount is None:
        return True
    clean_str = re.sub(r"[^\d.]", "", table_amount_str)
    try:
        tbl_val = float(clean_str)
        return abs(tbl_val - float(input_amount)) < 0.01
    except (ValueError, TypeError):
        return False

@mcp_tool_handler("list_draft_invoices")
async def list_draft_invoices(limit: int = 50) -> Dict[str, Any]:
    """
    Lists draft invoices with their real, matchable fields (sr_number, date, buyer, amount, type, status).
    Call this tool FIRST to obtain valid buyer names and dates to pass into edit_draft_invoice_field.
    """
    drafts_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.INVOICES_DRAFT}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(drafts_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
        await close_blocking_overlays(page)

        table = page.locator("table").first
        if not await table.is_visible(timeout=5000):
            return {
                "total_drafts": 0,
                "drafts": [],
                "message": "No invoices table found on drafts page."
            }

        rows = await page.locator("table tbody tr").all()
        drafts: List[Dict[str, Any]] = []

        for row in rows[:limit]:
            cols = [await td.inner_text() for td in await row.locator("td").all()]
            if len(cols) >= 6:
                drafts.append({
                    "sr_number": cols[0].strip(),
                    "date": cols[2].strip(),
                    "type": cols[3].strip(),
                    "buyer": cols[4].strip(),
                    "amount": cols[5].strip(),
                    "status": cols[6].strip() if len(cols) > 6 else "Draft"
                })

        return {
            "total_drafts": len(drafts),
            "drafts": drafts,
            "current_url": page.url
        }

@mcp_tool_handler("edit_draft_invoice_field")
async def edit_draft_invoice_field(
    buyer_name: str,
    date: str,
    field_name: str,
    new_value: str,
    amount: Optional[float] = None
) -> Dict[str, Any]:
    """
    Locates a draft invoice by buyer name and date (and optionally amount, if multiple
    drafts share the same buyer+date), then opens Invoice Studio to edit the specified field.
    """
    drafts_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.INVOICES_DRAFT}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(drafts_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
        await close_blocking_overlays(page)

        table = page.locator("table").first
        if not await table.is_visible(timeout=5000):
            raise ElementNotFoundError(f"Invoices table not found on {page.url}")

        rows = await page.locator("table tbody tr").all()
        matched_candidates = []

        for idx, row in enumerate(rows):
            cols = [await td.inner_text() for td in await row.locator("td").all()]
            if len(cols) >= 6:
                row_sr = cols[0].strip()
                row_date = cols[2].strip()
                row_buyer = cols[4].strip()
                row_amount = cols[5].strip()

                buyer_match = buyer_name.lower().strip() in row_buyer.lower().strip()
                date_match = _date_matches(date, row_date)

                if buyer_match and date_match:
                    matched_candidates.append({
                        "index": idx,
                        "row": row,
                        "sr_number": row_sr,
                        "date": row_date,
                        "buyer": row_buyer,
                        "amount": row_amount
                    })

        if not matched_candidates:
            raise ElementNotFoundError(
                f"No draft invoice found matching buyer='{buyer_name}' and date='{date}'. "
                "Call tool_list_draft_invoices first to see the currently available drafts."
            )

        # If amount specified, filter candidates
        if amount is not None:
            filtered = [c for c in matched_candidates if _amount_matches(amount, c["amount"])]
            if filtered:
                matched_candidates = filtered

        # Check for ambiguity
        if len(matched_candidates) > 1:
            candidate_list = [
                {"sr_number": c["sr_number"], "buyer": c["buyer"], "date": c["date"], "amount": c["amount"]}
                for c in matched_candidates
            ]
            raise ValueError(
                f"Multiple draft invoices match buyer='{buyer_name}' and date='{date}'. "
                f"Found {len(matched_candidates)} candidates: {candidate_list}. "
                "Please specify the exact 'amount' parameter to disambiguate."
            )

        target_candidate = matched_candidates[0]
        target_row = target_candidate["row"]

        # Click Actions button
        actions_btn = target_row.get_by_role("button", name=InvoiceListLocators.ROW_ACTIONS_BUTTON_TEXT).first
        if not await actions_btn.is_visible(timeout=2000):
            actions_btn = target_row.locator("button:has-text('Actions')").first
        await actions_btn.click()
        await page.wait_for_timeout(300)

        # Click Edit Invoice
        edit_opt = page.get_by_text(InvoiceListLocators.ACTION_MENU_EDIT_INVOICE, exact=True).first
        if not await edit_opt.is_visible(timeout=2000):
            raise ElementNotFoundError(
                f"Edit Invoice action not available for draft (SR# {target_candidate['sr_number']}, Buyer: {target_candidate['buyer']})."
            )
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

        # Click Save button ('Save Only' or 'Save')
        save_btn = page.get_by_role("button", name=re.compile(r"^(Save Only|Save)$", re.I)).first
        if not await save_btn.is_visible(timeout=2000):
            save_btn = page.locator("button:has-text('Save Only'), button:has-text('Save')").first

        if await save_btn.is_visible(timeout=2000):
            await save_btn.click()
        else:
            await page.keyboard.press("Enter")

        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)

        return {
            "matched_invoice": {
                "sr_number": target_candidate["sr_number"],
                "buyer": target_candidate["buyer"],
                "date": target_candidate["date"],
                "amount": target_candidate["amount"]
            },
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
