import asyncio
import logging
import os
import re
import time
from typing import AsyncGenerator, Optional, List
from contextlib import asynccontextmanager
from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError
)
from core.config import settings
from core.context import get_current_tenant_id
from db.supabase_client import db_service
from .selectors import PortalRoutes, LoginLocators

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
                    slow_mo=settings.SLOW_MO_MS if not settings.HEADLESS else 0,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu"
                    ]
                )
                logger.info(
                    f"Playwright Chromium browser launched successfully "
                    f"(headless={settings.HEADLESS}, slow_mo={settings.SLOW_MO_MS if not settings.HEADLESS else 0}ms)."
                )

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

    async def _capture_login_failure_diagnostics(self, page: Page, tenant_id: str) -> tuple[str, str]:
        """Capture page URL, visible body text, and a screenshot for diagnostic purposes."""
        current_url = page.url
        page_text = ""
        try:
            page_text = await page.inner_text("body")
        except Exception as e:
            logger.warning(f"Failed to extract page text for diagnostics: {e}")
            page_text = f"<failed to extract page text: {e}>"

        # Truncate for log
        truncated_log_text = page_text[:2000].strip()
        logger.error(
            f"Login failure diagnostics for tenant {tenant_id}:\n"
            f"  URL: {current_url}\n"
            f"  Page Text Excerpt (first 2000 chars):\n{truncated_log_text}"
        )

        # Save screenshot to debug_screenshots/ folder
        screenshot_dir = os.path.join(os.getcwd(), "debug_screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        safe_tenant_id = re.sub(r"[^a-zA-Z0-9_\-]", "_", tenant_id)
        timestamp = int(time.time())
        screenshot_filename = f"login_failure_{safe_tenant_id}_{timestamp}.png"
        screenshot_path = os.path.join(screenshot_dir, screenshot_filename)

        try:
            await page.screenshot(path=screenshot_path, full_page=True)
            logger.error(f"Saved login failure screenshot to: {screenshot_path}")
        except Exception as e:
            logger.warning(f"Failed to capture login failure screenshot: {e}")
            screenshot_path = f"<failed to save screenshot: {e}>"

        return page_text, screenshot_path

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

        # 1. Locate email input via confirmed placeholder
        email_loc = page.get_by_placeholder(LoginLocators.EMAIL_INPUT_PLACEHOLDER)
        if not await email_loc.is_visible(timeout=4000):
            # Fallback to type=email or role
            email_loc = page.locator("input[type='email']").first
        if not await email_loc.is_visible(timeout=3000):
            page_text, screenshot_path = await self._capture_login_failure_diagnostics(page, tenant_id)
            raise ElementNotFoundError(
                f"Could not locate login email input on {login_url} for tenant {tenant_id}. "
                f"Current URL: {page.url}. "
                f"Page text excerpt: {page_text[:300]!r}. "
                f"Screenshot saved: {screenshot_path}"
            )
        await email_loc.fill(credentials["email"])

        # 2. Locate password input via confirmed placeholder substring
        pw_loc = page.get_by_placeholder(re.compile(LoginLocators.PASSWORD_INPUT_PLACEHOLDER, re.IGNORECASE))
        if not await pw_loc.is_visible(timeout=4000):
            # Fallback to type=password
            pw_loc = page.locator("input[type='password']").first
        if not await pw_loc.is_visible(timeout=3000):
            page_text, screenshot_path = await self._capture_login_failure_diagnostics(page, tenant_id)
            raise ElementNotFoundError(
                f"Could not locate login password input on {login_url} for tenant {tenant_id}. "
                f"Current URL: {page.url}. "
                f"Page text excerpt: {page_text[:300]!r}. "
                f"Screenshot saved: {screenshot_path}"
            )
        await pw_loc.fill(credentials["password"])

        # 3. Submit form via confirmed role=button, name='Login'
        submit_btn = page.get_by_role("button", name=LoginLocators.SUBMIT_BUTTON_TEXT)
        if await submit_btn.is_visible(timeout=3000):
            await submit_btn.click()
        else:
            await page.keyboard.press("Enter")

        # 4. Wait for navigation away from /login OR explicit error to appear (avoid race condition on transient 'Logging in...' state)
        try:
            await page.wait_for_function(
                """() => {
                    const pathname = window.location.pathname.toLowerCase();
                    if (!pathname.includes('/login')) {
                        return true;
                    }
                    const text = (document.body ? document.body.innerText : "").toLowerCase();
                    const isStillLoading = text.includes('logging in...');
                    const hasErrorKeyword = (
                        text.includes('invalid') ||
                        text.includes('incorrect') ||
                        text.includes('credentials') ||
                        text.includes('does not exist') ||
                        text.includes('user not found') ||
                        text.includes('unauthorized') ||
                        text.includes('failed')
                    );
                    if (hasErrorKeyword && !isStillLoading) {
                        return true;
                    }
                    const errEl = document.querySelector("[role='alert'], .alert-danger, .error-message, .toast-error");
                    if (errEl && errEl.innerText && errEl.innerText.trim().length > 0 && !isStillLoading) {
                        return true;
                    }
                    return false;
                }""",
                timeout=settings.NAVIGATION_TIMEOUT_MS
            )
        except PlaywrightTimeoutError:
            logger.warning(
                f"Timed out after {settings.NAVIGATION_TIMEOUT_MS}ms waiting for post-login outcome on tenant {tenant_id}."
            )
            page_text, screenshot_path = await self._capture_login_failure_diagnostics(page, tenant_id)
            raise TenantAuthError(
                f"Login timed out waiting for redirect or error for tenant {tenant_id}. "
                f"Current URL: {page.url}. "
                f"Page text excerpt: {page_text[:300]!r}. "
                f"Screenshot saved: {screenshot_path}"
            )

        # Allow network activity to settle if route transitioned
        try:
            await page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass

        # Check for visible error message on the page
        err_locator = page.locator("[role='alert'], .alert-danger, .error-message, .toast-error").first
        err_text = ""
        try:
            if await err_locator.is_visible(timeout=1000):
                err_text = (await err_locator.inner_text()).strip()
        except Exception:
            err_text = ""

        # Verify post-login redirect (target: /dashboard or any non-login route)
        current_url = page.url
        if "/login" in current_url.lower():
            page_text, screenshot_path = await self._capture_login_failure_diagnostics(page, tenant_id)
            detail = f": {err_text}" if err_text else ""
            raise TenantAuthError(
                f"Login rejected by portal{detail} for tenant {tenant_id}. "
                f"Current URL: {current_url}. "
                f"Page text excerpt: {page_text[:300]!r}. "
                f"Screenshot saved: {screenshot_path}"
            )

        logger.info(f"Login successful for tenant {tenant_id} (navigated to {current_url}). Persisting storage_state...")
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

            await close_blocking_overlays(page)
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

async def close_blocking_overlays(page: Page) -> None:
    """
    Checks for and closes known persistent overlay panels that can cover page content.
    Specifically targets:
    - 'FBR Scenario Testing Specialist': A persistent floating widget/panel on the portal
      (frequently present in testing/sandbox tenants or auto-opened on fresh sessions)
      that visually masks dashboard cards, status metrics, and invoice tables.
    - Embedded iframes hosting scenario/chat testing assistants.
    - Generic modal backdrops, dialogs, or popups with visible Close buttons.

    Safe to call before any scraping operation — does nothing if no overlay is present.
    """
    try:
        # Diagnostic: Inspect and log all frames on the page
        for frame in page.frames:
            logger.info(f"Frame found: url={frame.url}, name={frame.name}")

        # Check for iframes or sub-frames containing the overlay
        for frame in page.frames:
            try:
                frame_overlay = frame.get_by_text("FBR Scenario Testing Specialist", exact=False).first
                if await frame_overlay.is_visible(timeout=500):
                    logger.info(f"Detected overlay inside frame url={frame.url}. Attempting to dismiss...")
                    frame_close = frame.locator("button", has_text=re.compile(r"^Close$", re.I)).first
                    if await frame_close.is_visible(timeout=500):
                        await frame_close.click(force=True)
                        logger.info("Successfully clicked Close button inside frame.")
                        await page.wait_for_timeout(300)
            except Exception:
                pass

        # Check top-level document for the overlay
        overlay_heading = page.get_by_text("FBR Scenario Testing Specialist", exact=False).first
        if await overlay_heading.is_visible(timeout=1500):
            logger.info("Detected 'FBR Scenario Testing Specialist' overlay panel in top DOM. Attempting to dismiss...")
            dismissed = False

            # 1. Target the specific Close button (avoiding Reset or other buttons with SVGs)
            close_candidates = [
                # Button specifically containing "Close" text
                page.locator("button", has_text=re.compile(r"^Close$", re.I)).first,
                page.get_by_role("button", name=re.compile(r"^Close$", re.I)).first,
                overlay_heading.locator("xpath=ancestor::*[contains(@class, 'fixed') or contains(@class, 'absolute') or contains(@class, 'z-') or @role='dialog'][1]").locator("button", has_text=re.compile(r"^Close$", re.I)).first,
                page.locator("button[aria-label*='close' i]").first,
                page.locator("button:has(.lucide-x)").first,
            ]

            for btn in close_candidates:
                try:
                    if await btn.is_visible(timeout=500):
                        await btn.click(force=True)
                        await page.wait_for_timeout(300)
                        if not await overlay_heading.is_visible(timeout=500):
                            dismissed = True
                            logger.info("Successfully dismissed overlay via Close button click.")
                            break
                except Exception:
                    continue

            # 2. Try Escape key if still visible
            if not dismissed and await overlay_heading.is_visible(timeout=300):
                try:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(300)
                    if not await overlay_heading.is_visible(timeout=500):
                        dismissed = True
                        logger.info("Successfully dismissed overlay via Escape key.")
                except Exception:
                    pass

            # 3. Fail-safe DOM neutralization: hide container if still visible
            if not dismissed and await overlay_heading.is_visible(timeout=300):
                logger.warning("Overlay close button click did not hide panel. Applying fail-safe DOM style removal...")
                try:
                    await page.evaluate(
                        """() => {
                            const elements = Array.from(document.querySelectorAll('*')).filter(
                                el => el.textContent && el.textContent.includes('FBR Scenario Testing Specialist')
                            );
                            for (const el of elements) {
                                const container = el.closest("[class*='fixed'], [class*='absolute'], [role='dialog'], aside, div.z-50, div.z-40");
                                if (container) {
                                    container.style.setProperty('display', 'none', 'important');
                                    container.style.setProperty('pointer-events', 'none', 'important');
                                    container.style.setProperty('visibility', 'hidden', 'important');
                                }
                            }
                        }"""
                    )
                    await page.wait_for_timeout(200)
                    logger.info("Fail-safe DOM style removal applied.")
                except Exception as e:
                    logger.debug(f"Fail-safe DOM removal encountered error: {e}")
    except Exception as e:
        # Never let overlay-closing failures break the actual tool call — this is a best-effort cleanup step.
        logger.debug(f"close_blocking_overlays encountered non-fatal error: {e}")

browser_manager = BrowserManager()
