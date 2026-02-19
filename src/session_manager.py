"""Session management for LinkedIn authentication using local persistent browser context"""

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


class SessionManager:
    """Manage browser sessions for LinkedIn authentication using local persistent context"""
    
    def __init__(self):
        """Initialize session manager"""
        # Get user data directory from env or use default
        user_data_dir = os.getenv('BROWSER_USER_DATA_DIR')
        if not user_data_dir:
            project_root = Path(__file__).parent.parent
            user_data_dir = str(project_root / '.browser_data')
        
        self.user_data_dir = user_data_dir
        self._playwright = None
        self._playwright_browser = None
        logger.info(f"Using persistent browser context: {self.user_data_dir}")
    
    def get_browser(self, headless: bool = False):
        """
        Get a browser-use Browser instance with persistent context for cookie/session storage
        (Backward compatibility method)
        
        Args:
            headless: Whether to run browser in headless mode
        
        Returns:
            Browser instance with persistent context
        """
        if not BROWSER_USE_AVAILABLE:
            raise ImportError("browser-use is not installed. Install with: pip install browser-use")
        
        try:
            # Create browser with persistent user data directory
            # This will save cookies, localStorage, and session data
            browser = Browser(
                headless=headless,
                user_data_dir=self.user_data_dir,
            )
            logger.info(f"Created browser-use browser with persistent context at: {self.user_data_dir}")
            return browser
        except Exception as e:
            logger.warning(f"Error creating browser with persistent context: {e}")
            logger.info("Falling back to default browser (no persistence)")
            # Fallback to default browser
            return Browser(headless=headless)
    
    async def get_playwright_browser(self, headless: bool = False) -> PlaywrightBrowser:
        """
        Get a Playwright Browser instance with persistent context for cookie/session storage
        
        Args:
            headless: Whether to run browser in headless mode
        
        Returns:
            Playwright Browser instance with persistent context
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError("playwright is not installed. Install with: pip install playwright && playwright install chromium")
        
        if self._playwright is None:
            self._playwright = await async_playwright().start()
        
        if self._playwright_browser is None:
            # Launch browser with persistent context
            self._playwright_browser = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=headless,
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                args=['--disable-blink-features=AutomationControlled']
            )
            logger.info(f"Created Playwright browser with persistent context at: {self.user_data_dir}")
        
        return self._playwright_browser
    
    async def get_playwright_context(self, headless: bool = False) -> BrowserContext:
        """
        Get a Playwright BrowserContext instance with persistent context
        
        Args:
            headless: Whether to run browser in headless mode
        
        Returns:
            Playwright BrowserContext instance
        """
        browser = await self.get_playwright_browser(headless=headless)
        # For persistent context, the browser itself is the context
        return browser
    
    async def close(self):
        """Close Playwright browser if open"""
        if self._playwright_browser:
            await self._playwright_browser.close()
            self._playwright_browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
