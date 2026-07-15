"""Session management for LinkedIn via real Chrome + CDP + dedicated profile.

Why not Playwright launch_persistent_context?
  Chrome for Testing / launchPersistentContext often shows
  "Something went wrong when opening your profile" after unclean shutdown
  or lock races (microsoft/playwright#35466). Cookie dump replay is also
  rejected by LinkedIn's fingerprint stack.

Approach used here (industry workaround):
  1. Launch system Google Chrome with --user-data-dir=<dedicated dir>
     and --remote-debugging-port=<port>
  2. Connect Playwright via connect_over_cdp
  3. One-time manual login; profile persists on disk
  4. Close via browser.close() then terminate Chrome process cleanly
"""

import asyncio
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

from src.utils.logger import logger

load_dotenv()

DEFAULT_PROFILE_DIR = ".linkedin_browser_profile"
DEFAULT_STORAGE_STATE_PATH = "linkedin_storage_state.json"
DEFAULT_CDP_PORT = 9333  # avoid clashing with ad-hoc 9222 tools

try:
    from browser_use import Browser

    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False
    Browser = None

try:
    from playwright.async_api import (
        Browser as PlaywrightBrowser,
        BrowserContext,
        Page,
        async_playwright,
    )

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    PlaywrightBrowser = None
    BrowserContext = None
    Page = None


class LinkedInNotLoggedInError(RuntimeError):
    """Raised when the persistent browser profile is not authenticated."""


class SessionManager:
    """Manage LinkedIn auth via a dedicated Chrome profile attached over CDP."""

    def __init__(self):
        project_root = Path(__file__).parent.parent
        profile_dir = (
            os.getenv("LINKEDIN_BROWSER_PROFILE_DIR")
            or os.getenv("BROWSER_USER_DATA_DIR")
            or str(project_root / DEFAULT_PROFILE_DIR)
        )
        # Absolute path required — relative user-data-dir is ignored/mis-resolved by Chrome
        self.user_data_dir = str(Path(profile_dir).expanduser().resolve())
        Path(self.user_data_dir).mkdir(parents=True, exist_ok=True)

        self.profile_directory = os.getenv("BROWSER_PROFILE_DIRECTORY")
        storage_path = os.getenv("LINKEDIN_STORAGE_STATE", DEFAULT_STORAGE_STATE_PATH)
        self.storage_state_path = str(Path(storage_path).expanduser().resolve())
        self.allow_storage_state_fallback = os.getenv(
            "ALLOW_STORAGE_STATE_FALLBACK", "false"
        ).lower() in ("1", "true", "yes")

        self.cdp_port = int(os.getenv("LINKEDIN_CDP_PORT", str(DEFAULT_CDP_PORT)))

        self._playwright = None
        self._playwright_browser: Optional[PlaywrightBrowser] = None
        self._playwright_context: Optional[BrowserContext] = None
        self._chrome_cdp_process: Optional[subprocess.Popen] = None
        self._using_persistent_context = False

        logger.info(f"LinkedIn browser profile directory: {self.user_data_dir}")

    def _find_chrome_executable(self) -> Optional[str]:
        chrome_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/google-chrome-stable",
            "/usr/bin/chromium",
            "/usr/bin/chromium-browser",
        ]
        for path in chrome_paths:
            if os.path.exists(path):
                return path
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            try:
                result = subprocess.run([name, "--version"], capture_output=True, timeout=5)
                if result.returncode == 0:
                    return name
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return None

    def _port_open(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def _clear_stale_profile_locks(self, *, force: bool = False) -> None:
        """Remove Chrome Singleton* lock files only when Chrome is not running for this profile."""
        if not force and self._chrome_cdp_process is not None:
            # NEVER clear locks under a live Chrome — that causes the
            # "Something went wrong when opening your profile" OK spam.
            if self._chrome_cdp_process.poll() is None:
                return

        profile = Path(self.user_data_dir)
        if not profile.exists():
            return
        removed = []
        for path in list(profile.glob("Singleton*")):
            try:
                path.unlink()
                removed.append(path.name)
            except OSError as e:
                logger.warning(f"Could not remove lock {path}: {e}")
        if removed:
            logger.info(f"Cleared stale Chrome profile locks: {', '.join(removed)}")

    def _sanitize_profile_prefs(self) -> None:
        """Mark last session as clean so Chrome doesn't show crash/profile recovery UI."""
        prefs_path = Path(self.user_data_dir) / "Default" / "Preferences"
        if not prefs_path.exists():
            return
        try:
            import json

            data = json.loads(prefs_path.read_text(encoding="utf-8"))
            profile = data.setdefault("profile", {})
            profile["exit_type"] = "Normal"
            session = data.setdefault("session", {})
            session["restore_on_startup"] = 5  # open new tab
            prefs_path.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            logger.debug(f"Could not sanitize Preferences: {e}")

    def _kill_orphaned_chrome_for_profile(self) -> None:
        """Best-effort kill of Chrome processes that still hold our user-data-dir."""
        try:
            result = subprocess.run(
                ["pgrep", "-fl", "Google Chrome|Chromium|chrome"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return
        marker = self.user_data_dir
        for line in (result.stdout or "").splitlines():
            if marker not in line:
                continue
            try:
                pid = int(line.split(None, 1)[0])
            except (ValueError, IndexError):
                continue
            try:
                os.kill(pid, 15)
                logger.info(f"Sent SIGTERM to orphaned Chrome pid={pid}")
            except ProcessLookupError:
                pass
            except PermissionError:
                logger.warning(f"No permission to kill pid={pid}")

    async def _ensure_playwright(self):
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError(
                "playwright is not installed. Install with: "
                "pip install playwright && playwright install chromium"
            )
        if self._playwright is None:
            self._playwright = await async_playwright().start()

    async def _wait_for_cdp(self, port: int, timeout_s: float = 30.0) -> None:
        deadline = time.time() + timeout_s
        url = f"http://127.0.0.1:{port}/json/version"
        while time.time() < deadline:
            try:
                await asyncio.to_thread(lambda: urllib.request.urlopen(url, timeout=1).read())
                return
            except Exception:
                await asyncio.sleep(0.4)
        raise RuntimeError(f"Chrome CDP not ready on port {port} within {timeout_s}s")

    async def _launch_chrome_cdp(self, headless: bool) -> subprocess.Popen:
        chrome_exe = self._find_chrome_executable()
        if not chrome_exe:
            raise RuntimeError(
                "Google Chrome not found. Install Chrome, then re-run "
                "python scripts/linkedin_login_once.py"
            )

        self._kill_orphaned_chrome_for_profile()
        await asyncio.sleep(0.5)
        self._clear_stale_profile_locks(force=True)
        self._sanitize_profile_prefs()

        if self._port_open(self.cdp_port):
            # Port busy — try next few ports
            for candidate in range(self.cdp_port, self.cdp_port + 20):
                if not self._port_open(candidate):
                    self.cdp_port = candidate
                    break
            else:
                raise RuntimeError(
                    f"No free CDP port near {self.cdp_port}. "
                    "Close other debugging Chrome instances."
                )

        cmd = [
            chrome_exe,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            # Suppress profile/crash error dialogs (clicking OK N times)
            # https://github.com/GoogleChrome/chrome-launcher/blob/main/docs/chrome-flags-for-tools.md
            "--noerrdialogs",
            "--disable-session-crashed-bubble",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=DevToolsDebuggingRestrictions,ChromeWhatsNewUI,TranslateUI",
            "--window-size=1920,1080",
        ]
        if headless:
            cmd.append("--headless=new")
        cmd.append("about:blank")

        logger.info(
            f"Launching system Chrome via CDP "
            f"(port={self.cdp_port}, profile={self.user_data_dir})"
        )
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            await self._wait_for_cdp(self.cdp_port, timeout_s=40)
        except Exception:
            process.terminate()
            raise
        logger.info(f"Chrome CDP ready on http://127.0.0.1:{self.cdp_port}")
        return process

    async def get_playwright_context(self, headless: bool = False) -> BrowserContext:
        """Launch Chrome (dedicated profile) and attach Playwright over CDP."""
        await self._ensure_playwright()

        if self._playwright_context is not None:
            return self._playwright_context

        self._chrome_cdp_process = await self._launch_chrome_cdp(headless=headless)
        cdp_url = f"http://127.0.0.1:{self.cdp_port}"
        browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
        self._playwright_browser = browser

        if browser.contexts:
            context = browser.contexts[0]
        else:
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080}
            )

        self._playwright_context = context
        self._using_persistent_context = True
        logger.info("Playwright attached to Chrome over CDP")
        return context

    async def get_page(self, headless: bool = False) -> Page:
        context = await self.get_playwright_context(headless=headless)
        if context.pages:
            page = context.pages[0]
        else:
            page = await context.new_page()
        page.on("dialog", lambda dialog: dialog.dismiss())
        return page

    async def get_playwright_browser(self, headless: bool = False):
        """Compatibility wrapper — returns CDP-connected Browser."""
        await self.get_playwright_context(headless=headless)
        return self._playwright_browser or _PersistentBrowserShim(self._playwright_context)

    async def _login_signals(self, page: Page, *, navigate: bool = False) -> dict:
        try:
            cookies = await page.context.cookies(
                ["https://www.linkedin.com", "https://linkedin.com"]
            )
            has_li_at = any(c.get("name") == "li_at" and c.get("value") for c in cookies)
        except Exception:
            has_li_at = False

        if navigate:
            await page.goto(
                "https://www.linkedin.com/feed/",
                wait_until="domcontentloaded",
                timeout=60000,
            )
            await asyncio.sleep(2)

        try:
            signals = await page.evaluate(
                """() => {
                  const text = document.body ? document.body.innerText : '';
                  return {
                    joinNow: text.includes('Join now'),
                    signInModal: text.includes('Sign in to view more jobs')
                      || text.includes('Sign in to view'),
                    hasSignInBtn: !!document.querySelector(
                      'a[data-tracking-control-name*=\"guest_homepage\"], a[href*=\"/login\"]'
                    ),
                    hasMeMenu: !!document.querySelector(
                      '.global-nav__me, img.global-nav__me-photo, button.global-nav__primary-link-me-menu-trigger'
                    ),
                    hasGlobalNav: !!document.querySelector('#global-nav, nav.global-nav'),
                    url: location.href,
                    title: document.title,
                  };
                }"""
            )
        except Exception as e:
            # Caller may retry; preserve cookie signal at least
            if "Execution context was destroyed" in str(e) or "navigation" in str(e).lower():
                raise
            logger.debug(f"evaluate failed: {e}")
            signals = {
                "joinNow": False,
                "signInModal": False,
                "hasSignInBtn": False,
                "hasMeMenu": False,
                "hasGlobalNav": False,
                "url": getattr(page, "url", "") or "",
                "title": "",
            }
        signals["has_li_at"] = has_li_at
        return signals

    def _is_logged_in_from_signals(self, signals: dict) -> bool:
        if signals.get("signInModal"):
            return False
        if signals.get("joinNow") and not signals.get("hasMeMenu"):
            return False
        url = signals.get("url") or ""
        on_app = any(
            p in url
            for p in ("/feed", "/jobs", "/mynetwork", "/messaging", "/notifications", "/in/")
        )
        if signals.get("has_li_at") and (signals.get("hasMeMenu") or on_app):
            return True
        if signals.get("hasMeMenu") and on_app:
            return True
        return False

    async def assert_logged_in(self, page: Optional[Page] = None) -> bool:
        if page is None:
            page = await self.get_page(headless=False)
        signals = await self._login_signals(page, navigate=True)
        if not self._is_logged_in_from_signals(signals):
            raise LinkedInNotLoggedInError(
                "LinkedIn session is not logged in (guest wall / missing li_at).\n"
                f"Signals: {signals}\n"
                "Run: python scripts/linkedin_login_once.py\n"
                "Log in manually in the opened browser, then re-run your command."
            )
        logger.info("LinkedIn session authenticated (CDP Chrome profile)")
        return True

    async def wait_for_manual_login(self, page: Page, timeout_seconds: int = 600) -> bool:
        """Poll for login without navigating away from the login page."""
        logger.info(
            f"Waiting up to {timeout_seconds}s for manual LinkedIn login "
            "(page will not auto-refresh)..."
        )
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while asyncio.get_event_loop().time() < deadline:
            try:
                signals = await self._login_signals(page, navigate=False)
            except Exception as e:
                # LinkedIn often navigates during login/2FA; that destroys the
                # JS world mid-evaluate — retry instead of aborting.
                msg = str(e)
                if "Execution context was destroyed" in msg or "navigation" in msg.lower():
                    logger.debug(f"Login poll interrupted by navigation: {e}")
                    await asyncio.sleep(1.5)
                    continue
                logger.warning(f"Login poll error (will retry): {e}")
                await asyncio.sleep(2)
                continue

            if self._is_logged_in_from_signals(signals):
                logger.info("Login detected; verifying on feed...")
                try:
                    await self.assert_logged_in(page)
                    return True
                except Exception as e:
                    msg = str(e)
                    if "Execution context was destroyed" in msg or "navigation" in msg.lower():
                        await asyncio.sleep(2)
                        continue
                    if isinstance(e, LinkedInNotLoggedInError):
                        await asyncio.sleep(2)
                        continue
                    raise

            try:
                url = (page.url or "").lower()
            except Exception:
                url = ""
            if url and "linkedin.com" not in url:
                try:
                    await page.goto(
                        "https://www.linkedin.com/login",
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                except Exception as e:
                    logger.debug(f"Could not return to login page: {e}")

            await asyncio.sleep(2)
        raise LinkedInNotLoggedInError(
            f"Timed out after {timeout_seconds}s waiting for LinkedIn login.\n"
            "Run scripts/linkedin_login_once.py again and finish signing in."
        )

    async def get_browser_via_playwright(self, headless: bool = False):
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use is not installed.")
        await self.get_playwright_context(headless=headless)
        cdp_url = f"http://127.0.0.1:{self.cdp_port}"
        return Browser(cdp_url=cdp_url, is_local=True)

    def get_browser(self, headless: bool = False):
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use is not installed.")
        try:
            return Browser(
                headless=headless,
                user_data_dir=self.user_data_dir,
                channel="chrome",
            )
        except Exception as e:
            logger.warning(f"browser-use persistent browser failed: {e}")
            return Browser(headless=headless)

    def _get_context(self) -> Optional[BrowserContext]:
        return self._playwright_context

    async def close(self):
        """Close CDP browser cleanly (avoids profile corruption / SingletonLocks)."""
        # Playwright maintainers: call browser.close() so Chrome exits fully (#35466)
        if self._playwright_browser is not None:
            try:
                await self._playwright_browser.close()
            except Exception as e:
                logger.debug(f"browser.close error: {e}")
        self._playwright_browser = None
        self._playwright_context = None
        self._using_persistent_context = False

        if self._chrome_cdp_process is not None:
            try:
                self._chrome_cdp_process.terminate()
                self._chrome_cdp_process.wait(timeout=8)
            except Exception:
                try:
                    self._chrome_cdp_process.kill()
                except Exception:
                    pass
            self._chrome_cdp_process = None

        self._kill_orphaned_chrome_for_profile()
        self._clear_stale_profile_locks(force=True)
        self._sanitize_profile_prefs()

        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None


class _PersistentBrowserShim:
    def __init__(self, context: BrowserContext):
        self._context = context
        self.contexts = [context]

    async def new_context(self, **kwargs):
        return self._context

    async def close(self):
        await self._context.close()
