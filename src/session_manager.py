"""Session management for LinkedIn authentication using cookie-based storage state"""

import asyncio
import os
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from src.utils.logger import logger

load_dotenv()

# CDP port for manual Chrome launch (used when connecting browser-use to Playwright's Chromium)
CDP_DEBUG_PORT = 9222

# Try to import browser-use for backward compatibility
try:
    from browser_use import Browser
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False
    Browser = None

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Browser as PlaywrightBrowser, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    PlaywrightBrowser = None
    BrowserContext = None

# Default path for LinkedIn cookies (exported via chrome-cookies-to-playwright)
DEFAULT_STORAGE_STATE_PATH = "linkedin_storage_state.json"


class SessionManager:
    """Manage browser sessions for LinkedIn authentication using cookie storage state"""
    
    def __init__(self):
        """Initialize session manager"""
        user_data_dir = os.getenv('BROWSER_USER_DATA_DIR')
        if not user_data_dir:
            project_root = Path(__file__).parent.parent
            user_data_dir = str(project_root / '.browser_data')
        
        self.user_data_dir = str(Path(user_data_dir).expanduser().resolve())
        self.profile_directory = os.getenv('BROWSER_PROFILE_DIRECTORY')
        self._playwright = None
        self._playwright_browser = None
        self._chrome_cdp_process = None
        
        # Path to LinkedIn cookies (from chrome-cookies-to-playwright export)
        storage_path = os.getenv('LINKEDIN_STORAGE_STATE', DEFAULT_STORAGE_STATE_PATH)
        self.storage_state_path = str(Path(storage_path).expanduser().resolve())
        
        logger.info(f"Using storage state for LinkedIn auth: {self.storage_state_path}")
    
    def _find_chromium_executable(self) -> Optional[str]:
        """Find Chrome/Chromium executable for manual CDP launch."""
        # Platform-specific paths (same as browser-use Playwright integration example)
        chrome_paths = [
            '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',  # macOS
            '/usr/bin/google-chrome',  # Linux
            '/usr/bin/google-chrome-stable',  # Linux
            '/usr/bin/chromium',  # Linux (Raspberry Pi)
            '/usr/bin/chromium-browser',  # Linux
            'chromium',  # PATH
            'google-chrome',  # PATH
        ]
        for path in chrome_paths:
            if path in ('chromium', 'google-chrome'):
                try:
                    result = subprocess.run(
                        [path, '--version'],
                        capture_output=True,
                        timeout=5,
                    )
                    if result.returncode == 0:
                        return path
                except (FileNotFoundError, subprocess.TimeoutExpired):
                    continue
            elif os.path.exists(path):
                return path
        return None

    async def _launch_chrome_with_cdp(self, headless: bool) -> subprocess.Popen:
        """Launch Chrome/Chromium with CDP debugging port. Returns the process."""
        chrome_exe = self._find_chromium_executable()
        if not chrome_exe:
            raise RuntimeError(
                "Chrome/Chromium not found. Install with: "
                "macOS: brew install --cask google-chrome | "
                "Linux/Raspberry Pi: sudo apt install chromium-browser"
            )
        user_data_dir = tempfile.mkdtemp(prefix='chrome_cdp_')
        cmd = [
            chrome_exe,
            f'--remote-debugging-port={CDP_DEBUG_PORT}',
            f'--user-data-dir={user_data_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-extensions',
            '--disable-blink-features=AutomationControlled',
        ]
        if headless:
            cmd.extend(['--headless=new', '--disable-gpu'])
        cmd.append('about:blank')
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Wait for CDP to be ready
        def _check_cdp():
            with urllib.request.urlopen(
                f'http://127.0.0.1:{CDP_DEBUG_PORT}/json/version',
                timeout=1,
            ):
                pass

        for _ in range(20):
            try:
                await asyncio.to_thread(_check_cdp)
                logger.info(f"Chrome started with CDP on port {CDP_DEBUG_PORT}")
                return process
            except Exception:
                await asyncio.sleep(1)
        process.terminate()
        raise RuntimeError("Chrome failed to start with CDP within 20 seconds")

    async def get_browser_via_playwright(self, headless: bool = False):
        """
        Get a browser-use Browser instance connected to Chromium via CDP.
        Launches Chrome/Chromium manually with --remote-debugging-port, then connects
        both Playwright and browser-use to it. More reliable on Raspberry Pi where
        browser-use's direct Chrome launch may fail.
        
        Note: Playwright Python does not have launch_server(), so we launch Chrome manually.
        """
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use is not installed. Install with: pip install browser-use")
        
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("playwright is not installed. Install with: pip install playwright && playwright install chromium")
        
        if not os.path.exists(self.storage_state_path):
            raise FileNotFoundError(
                f"LinkedIn storage state not found: {self.storage_state_path}\n"
                "Run: python scripts/export_linkedin_cookies.py\n"
                "This exports your Chrome LinkedIn cookies for automation."
            )
        
        cdp_url = f"http://127.0.0.1:{CDP_DEBUG_PORT}"
        
        try:
            # Launch Chrome with CDP if not already running
            if self._playwright_browser is None:
                logger.info("Launching Chrome with CDP for browser-use + Playwright connection...")
                
                self._chrome_cdp_process = await self._launch_chrome_with_cdp(headless)
                
                if self._playwright is None:
                    self._playwright = await async_playwright().start()
                
                # Connect Playwright to the Chrome instance
                self._playwright_browser = await self._playwright.chromium.connect_over_cdp(cdp_url)
                
                # Create context with LinkedIn cookies
                self._playwright_context = await self._playwright_browser.new_context(
                    storage_state=self.storage_state_path,
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                )
                
                logger.info("Playwright connected to Chrome with LinkedIn session")
            
            logger.info(f"Connecting browser-use to Chromium via CDP: {cdp_url}")
            
            # Connect browser-use to the same Chrome instance
            browser = Browser(cdp_url=cdp_url, is_local=True)
            logger.info("Successfully connected browser-use to Chromium")
            
            return browser
        except Exception as e:
            logger.warning(f"Failed to use CDP approach: {e}. Falling back to direct browser-use.")
            return self.get_browser(headless=headless)
    
    def get_browser(self, headless: bool = False):
        """
        Get a browser-use Browser instance with persistent context for cookie/session storage
        (Backward compatibility method)
        
        Note: On Raspberry Pi or systems with CDP issues, use get_browser_via_playwright() instead.
        """
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use is not installed. Install with: pip install browser-use")
        
        try:
            browser_kwargs = {
                "headless": headless,
                "user_data_dir": self.user_data_dir,
                "channel": "chrome",
            }
            if self.profile_directory:
                browser_kwargs["profile_directory"] = self.profile_directory
            browser = Browser(**browser_kwargs)
            logger.info(f"Created browser-use browser with persistent context at: {self.user_data_dir}")
            return browser
        except Exception as e:
            logger.warning(f"Error creating browser with persistent context: {e}")
            logger.info("Falling back to default browser (no persistence)")
            return Browser(headless=headless)
    
    async def get_playwright_browser(self, headless: bool = False) -> PlaywrightBrowser:
        """
        Get a Playwright Browser with LinkedIn cookies loaded from storage state.
        Requires running `python scripts/export_linkedin_cookies.py` first (one-time setup).
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("playwright is not installed. Install with: pip install playwright && playwright install chromium")
        
        if not os.path.exists(self.storage_state_path):
            raise FileNotFoundError(
                f"LinkedIn storage state not found: {self.storage_state_path}\n"
                "Run: python scripts/export_linkedin_cookies.py\n"
                "This exports your Chrome LinkedIn cookies for automation. "
                "Requires Full Disk Access on macOS (System Settings → Privacy & Security)."
            )
        
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        
        if self._playwright_browser is None:
            logger.info("Launching Playwright browser with LinkedIn cookies...")
            
            browser = await self._playwright.chromium.launch(
                headless=headless,
                args=['--disable-blink-features=AutomationControlled'],
            )
            
            # Create context with LinkedIn cookies from exported storage state
            context = await browser.new_context(
                storage_state=self.storage_state_path,
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            )
            
            # Store browser - job scraper will get context and page from it
            self._playwright_browser = browser
            self._playwright_context = context
            
            logger.info("Playwright browser launched with LinkedIn session")
        
        return self._playwright_browser
    
    def _get_context(self) -> Optional[BrowserContext]:
        """Get the context with LinkedIn cookies (used by job scraper)"""
        return getattr(self, '_playwright_context', None)
    
    async def get_playwright_context(self, headless: bool = False) -> BrowserContext:
        """Get a Playwright BrowserContext with LinkedIn cookies loaded"""
        await self.get_playwright_browser(headless=headless)
        return self._playwright_context
    
    async def close(self):
        """Close Playwright browser and Chrome CDP process"""
        if self._playwright_browser:
            await self._playwright_browser.close()
            self._playwright_browser = None
            self._playwright_context = None
        if getattr(self, '_chrome_cdp_process', None):
            self._chrome_cdp_process.terminate()
            try:
                self._chrome_cdp_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_cdp_process.kill()
            self._chrome_cdp_process = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
