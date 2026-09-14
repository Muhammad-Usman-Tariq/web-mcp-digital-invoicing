import asyncio
import logging
from typing import AsyncGenerator, Optional, List, Dict, Any
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Playwright, Browser, BrowserContext, Page, Error as PlaywrightError
from core.config import settings
from core.context import get_current_tenant_id
from db.supabase_client import db_service
from .selectors import PortalRoutes, LoginSelectors

logger = logging.getLogger("digital-invoice-web.browser")

class BrowserSessionError(Exception):
    """Base error for browser session and automation failures."""
    pass

class TenantAuthError(BrowserSessionError):
    """Raised when tenant is inactive or credentials cannot authenticate."""
    pass

class ElementNotFoundError(BrowserSessionError):
    """Raised when an expected DOM element is not found."""
    pass

class BrowserManager:
    def __init__(self):
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._lock = asyncio.Lock()

    async def get_semaphore(self) -> asyncio.Semaphore:
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_BROWSERS)
        return self._semaphore

    async def start(self):
        """Initialize global Playwright process and shared Chromium browser."""
        async with self._lock:
            if not self._playwright:
                logger.info("Starting Playwright driver...")
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=settings.HEADLESS,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu"
                    ]
                )
                logger.info("Playwright Chromium browser launched successfully.")

    async def stop(self):
        """Gracefully stop shared browser and Playwright process."""
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.warning(f"Error closing browser: {e}")
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning(f"Error stopping playwright: {e}")
                self._playwright = None
            logger.info("Playwright stopped.")

    async def find_element(
        self,
        page: Page,
        candidate_selectors: List[str],
        timeout_ms: int = 5000
    ) -> Optional[str]:
        """Test candidate selectors in priority order and return the first matched selector."""
        per_selector_timeout = max(1000, timeout_ms // max(1, len(candidate_selectors)))
        for selector in candidate_selectors:
            try:
                locator = page.locator(selector).first
                if await locator.is_visible(timeout=per_selector_timeout):
                    return selector
            except Exception:
                continue
        return None

    async def _perform_login(self, page: Page, context: BrowserContext, tenant_id: str):
        """Drive the real UI login flow with decrypted credentials and cache session."""
        credentials = await db_service.get_decrypted_credentials(tenant_id)
        if not credentials:
            raise TenantAuthError(
                f"No credentials configured for tenant '{tenant_id}'. Onboard credentials first."
            )

        login_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.LOGIN}"
        logger.info(f"Navigating to login page: {login_url} for tenant {tenant_id}")
        
        try:
            await page.goto(login_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
        except Exception as e:
            logger.warning(f"Initial login page navigation reached timeout or partial load: {e}")

        # 1. Locate email input
        email_sel = await self.find_element(page, LoginSelectors.EMAIL_INPUT, timeout_ms=8000)
        if not email_sel:
            raise ElementNotFoundError(
                f"Could not locate login email input on {login_url}. Candidate selectors: {LoginSelectors.EMAIL_INPUT}"
            )
        await page.fill(email_sel, credentials["email"])

        # 2. Locate password input
        pw_sel = await self.find_element(page, LoginSelectors.PASSWORD_INPUT, timeout_ms=5000)
        if not pw_sel:
            raise ElementNotFoundError(
                f"Could not locate login password input on {login_url}. Candidate selectors: {LoginSelectors.PASSWORD_INPUT}"
            )
        await page.fill(pw_sel, credentials["password"])

        # 3. Submit form
        submit_sel = await self.find_element(page, LoginSelectors.SUBMIT_BUTTON, timeout_ms=5000)
        if not submit_sel:
            # Fallback to pressing Enter
            await page.keyboard.press("Enter")
        else:
            await page.click(submit_sel)

        # 4. Wait for navigation or error
        try:
            await page.wait_for_load_state("networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
        except Exception:
            pass

        # Check for visible error message on the page
        err_sel = await self.find_element(page, LoginSelectors.LOGIN_ERROR_MESSAGE, timeout_ms=2000)
        if err_sel:
            err_text = await page.locator(err_sel).first.inner_text()
            raise TenantAuthError(f"Login rejected by portal: {err_text.strip()}")

        # Verify we navigated away from /login
        current_url = page.url
        if "/login" in current_url.lower():
            # Check if logged in indicator is present despite URL
            indicator = await self.find_element(page, LoginSelectors.LOGGED_IN_INDICATOR, timeout_ms=3000)
            if not indicator:
                raise TenantAuthError(
                    f"Authentication failed: Page remained at {current_url} after submitting credentials."
                )

        logger.info(f"Login successful for tenant {tenant_id}. Persisting storage_state...")
        storage_state = await context.storage_state()
        await db_service.save_session(tenant_id, storage_state)

    @asynccontextmanager
    async def get_tenant_page(self, tenant_id: Optional[str] = None) -> AsyncGenerator[Page, None]:
        """
        Context manager that yields an authenticated Page inside an isolated BrowserContext.
        Enforces concurrency semaphore, tenant isolation, and session reuse with login fallback.
        """
        resolved_tenant_id = tenant_id or get_current_tenant_id()
        if not resolved_tenant_id:
            raise TenantAuthError("Missing tenant_id in request context.")

        # Verify tenant active status if DB configured
        tenant_info = await db_service.get_tenant(resolved_tenant_id)
        if tenant_info and not tenant_info.get("is_active", True):
            raise TenantAuthError(f"Tenant '{resolved_tenant_id}' is deactivated.")

        sem = await self.get_semaphore()
        try:
            # Wait up to 30s to acquire browser concurrency slot
            await asyncio.wait_for(sem.acquire(), timeout=30.0)
        except asyncio.TimeoutError:
            raise BrowserSessionError(
                f"Server is busy: Concurrency limit ({settings.MAX_CONCURRENT_BROWSERS}) reached. Please retry shortly."
            )

        if not self._browser:
            await self.start()

        context: Optional[BrowserContext] = None
        page: Optional[Page] = None
        try:
            # Check for cached valid storage_state
            cached_session = await db_service.get_valid_session(resolved_tenant_id)
            if cached_session:
                logger.info(f"Reusing cached storage_state for tenant {resolved_tenant_id}")
                context = await self._browser.new_context(
                    storage_state=cached_session,
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
            else:
                logger.info(f"No cached session for tenant {resolved_tenant_id}. Initializing fresh context...")
                context = await self._browser.new_context(
                    viewport={"width": 1280, "height": 800},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )

            # Set global timeouts
            context.set_default_navigation_timeout(settings.NAVIGATION_TIMEOUT_MS)
            context.set_default_timeout(settings.ACTION_TIMEOUT_MS)
            page = await context.new_page()

            # Verify session or trigger login
            if cached_session:
                test_url = f"{settings.PORTAL_BASE_URL.rstrip('/')}{PortalRoutes.DASHBOARD}"
                try:
                    await page.goto(test_url, wait_until="networkidle", timeout=settings.NAVIGATION_TIMEOUT_MS)
                    if "/login" in page.url.lower():
                        logger.warning(f"Cached session for tenant {resolved_tenant_id} expired on portal. Re-authenticating...")
                        await db_service.invalidate_session(resolved_tenant_id)
                        await self._perform_login(page, context, resolved_tenant_id)
                except Exception as e:
                    logger.warning(f"Session verification check encountered error ({e}). Attempting fresh login...")
                    await self._perform_login(page, context, resolved_tenant_id)
            else:
                await self._perform_login(page, context, resolved_tenant_id)

            yield page

        finally:
            if page:
                try:
                    await page.close()
                except Exception as e:
                    logger.debug(f"Error closing page: {e}")
            if context:
                try:
                    await context.close()
                except Exception as e:
                    logger.debug(f"Error closing context: {e}")
            sem.release()

browser_manager = BrowserManager()
