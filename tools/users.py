import logging
from typing import Dict, Any
from core.config import settings
from browser.manager import browser_manager, ElementNotFoundError
from browser.selectors import PortalRoutes, UserSelectors
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.users")

@mcp_tool_handler("add_new_user")
async def add_new_user(
    name: str,
    email: str,
    role: str = "User"
) -> Dict[str, Any]:
    """
    Fills the Add User form on the portal user management screen, handles confirmation dialog,
    and returns the created user details.
    """
    users_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.USERS}"
    async with browser_manager.get_tenant_page() as page:
        await page.goto(users_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        # 1. Click "Add User" button
        add_btn_sel = await browser_manager.find_element(page, UserSelectors.ADD_USER_BUTTON, timeout_ms=4000)
        if not add_btn_sel:
            raise ElementNotFoundError(f"Add User button not found. Candidates: {UserSelectors.ADD_USER_BUTTON}")
        await page.click(add_btn_sel)

        # 2. Wait for modal / form
        await page.wait_for_timeout(1000)

        # 3. Fill Name
        name_sel = await browser_manager.find_element(page, UserSelectors.USER_NAME_INPUT, timeout_ms=3000)
        if not name_sel:
            raise ElementNotFoundError(f"User Name input not found on Add User form. Candidates: {UserSelectors.USER_NAME_INPUT}")
        await page.fill(name_sel, name)

        # 4. Fill Email
        email_sel = await browser_manager.find_element(page, UserSelectors.USER_EMAIL_INPUT, timeout_ms=3000)
        if not email_sel:
            raise ElementNotFoundError(f"User Email input not found on Add User form. Candidates: {UserSelectors.USER_EMAIL_INPUT}")
        await page.fill(email_sel, email)

        # 5. Select Role if role select exists
        role_sel = await browser_manager.find_element(page, UserSelectors.USER_ROLE_SELECT, timeout_ms=2000)
        if role_sel:
            try:
                await page.select_option(role_sel, label=role)
            except Exception:
                try:
                    await page.select_option(role_sel, value=role.lower())
                except Exception:
                    pass

        # 6. Click Confirm / Submit button
        confirm_sel = await browser_manager.find_element(page, UserSelectors.CONFIRM_BUTTON, timeout_ms=3000)
        if not confirm_sel:
            raise ElementNotFoundError(f"Confirmation button not found. Candidates: {UserSelectors.CONFIRM_BUTTON}")
        await page.click(confirm_sel)

        # 7. Check for secondary confirmation dialog
        try:
            sec_confirm = page.locator("button:has-text('Yes'), button:has-text('OK'), .swal2-confirm").first
            if await sec_confirm.is_visible(timeout=2000):
                await sec_confirm.click()
        except Exception:
            pass

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        return {
            "status": "created",
            "name": name,
            "email": email,
            "role": role,
            "message": f"User '{name}' ({email}) successfully created on portal.",
            "current_url": page.url
        }
