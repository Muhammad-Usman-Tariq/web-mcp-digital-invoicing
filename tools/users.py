import re
import secrets
import string
import logging
from typing import Dict, Any, Optional
from core.config import settings
from browser.manager import browser_manager, ElementNotFoundError, close_blocking_overlays
from browser.selectors import PortalRoutes, UsersLocators
from .base import mcp_tool_handler

logger = logging.getLogger("digital-invoice-web.tools.users")

def _generate_temporary_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))

@mcp_tool_handler("add_new_user")
async def add_new_user(
    full_name: str,
    email: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    company: Optional[str] = None,
    role: str = "Company Admin"
) -> Dict[str, Any]:
    """
    Fills the Add User modal on /users using the confirmed accessibility tree locators:
    full_name, username, email, password, company combobox, role combobox, and submits.
    """
    users_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.USERS}"
    resolved_username = username or email.split("@")[0]
    resolved_password = password or _generate_temporary_password()

    async with browser_manager.get_tenant_page() as page:
        await page.goto(users_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
        await close_blocking_overlays(page)

        # 1. Click "Add User" button
        add_btn = page.get_by_role("button", name=UsersLocators.ADD_USER_BUTTON[1]).first
        if not await add_btn.is_visible(timeout=4000):
            raise ElementNotFoundError(f"Add User button not found on {page.url}.")
        await add_btn.click()

        # 2. Wait for modal (role=dialog)
        dialog = page.get_by_role("dialog").first
        await page.wait_for_timeout(500)

        # 3. Fill Username
        uname_input = page.get_by_placeholder(UsersLocators.USERNAME_INPUT_PLACEHOLDER).first
        if await uname_input.is_visible(timeout=3000):
            await uname_input.fill(resolved_username)

        # 4. Fill Full Name
        fname_input = page.get_by_placeholder(UsersLocators.FULL_NAME_INPUT_PLACEHOLDER).first
        if await fname_input.is_visible(timeout=3000):
            await fname_input.fill(full_name)

        # 5. Fill Email
        email_input = page.get_by_placeholder(UsersLocators.EMAIL_INPUT_PLACEHOLDER).first
        if await email_input.is_visible(timeout=3000):
            await email_input.fill(email)

        # 6. Fill Password
        pw_input = page.get_by_placeholder(UsersLocators.PASSWORD_INPUT_PLACEHOLDER).first
        if await pw_input.is_visible(timeout=3000):
            await pw_input.fill(resolved_password)

        # 7. Select Company if provided / combobox present
        combos = await page.get_by_role("combobox").all()
        if company and len(combos) > UsersLocators.COMPANY_COMBOBOX_INDEX:
            try:
                await combos[UsersLocators.COMPANY_COMBOBOX_INDEX].click()
                company_opt = page.get_by_text(company, exact=False).first
                if await company_opt.is_visible(timeout=1500):
                    await company_opt.click()
            except Exception as e:
                logger.debug(f"Company combobox select error: {e}")

        # 8. Select Role if combobox present
        if role and len(combos) > UsersLocators.ROLE_COMBOBOX_INDEX:
            try:
                await combos[UsersLocators.ROLE_COMBOBOX_INDEX].click()
                role_opt = page.get_by_text(role, exact=False).first
                if await role_opt.is_visible(timeout=1500):
                    await role_opt.click()
            except Exception as e:
                logger.debug(f"Role combobox select error: {e}")

        # 9. Click submit / confirmation button in dialog
        submit_btn = dialog.get_by_role("button", name=re.compile(r"(Create|Save|Add|Submit)", re.I)).first
        if not await submit_btn.is_visible(timeout=2000):
            submit_btn = page.get_by_role("button", name=re.compile(r"(Create|Save|Add|Submit)", re.I)).first

        if await submit_btn.is_visible(timeout=2000):
            await submit_btn.click()
        else:
            await page.keyboard.press("Enter")

        # 10. Secondary confirmation if any
        try:
            confirm_sec = page.locator("button:has-text('Confirm'), button:has-text('OK'), .swal2-confirm").first
            if await confirm_sec.is_visible(timeout=1500):
                await confirm_sec.click()
        except Exception:
            pass

        await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)

        return {
            "status": "created",
            "username": resolved_username,
            "full_name": full_name,
            "email": email,
            "role": role,
            "company": company,
            "message": f"User '{full_name}' ({resolved_username}) successfully created on portal.",
            "current_url": page.url
        }
