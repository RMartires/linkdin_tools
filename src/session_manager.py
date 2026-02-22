"""Session management for LinkedIn authentication using cookie-based storage state"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

from src.utils.logger import logger

load_dotenv()

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
        
        # Path to LinkedIn cookies (from chrome-cookies-to-playwright export)
        storage_path = os.getenv('LINKEDIN_STORAGE_STATE', DEFAULT_STORAGE_STATE_PATH)
        self.storage_state_path = str(Path(storage_path).expanduser().resolve())
        
        logger.info(f"Using storage state for LinkedIn auth: {self.storage_state_path}")
    
    def get_browser(self, headless: bool = False):
        """
        Get a browser-use Browser instance with persistent context for cookie/session storage
        (Backward compatibility method)
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
        """Close Playwright browser"""
        if self._playwright_browser:
            await self._playwright_browser.close()
            self._playwright_browser = None
            self._playwright_context = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
