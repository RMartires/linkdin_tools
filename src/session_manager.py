"""Session management for LinkedIn authentication using local persistent browser context"""

import os
from pathlib import Path
from typing import Optional
from browser_use import Browser
from dotenv import load_dotenv

from src.utils.logger import logger

load_dotenv()


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
        logger.info(f"Using persistent browser context: {self.user_data_dir}")
    
    def get_browser(self, headless: bool = False) -> Browser:
        """
        Get a Browser instance with persistent context for cookie/session storage
        
        Args:
            headless: Whether to run browser in headless mode
        
        Returns:
            Browser instance with persistent context
        """
        try:
            # Create browser with persistent user data directory
            # This will save cookies, localStorage, and session data
            browser = Browser(
                headless=headless,
                user_data_dir=self.user_data_dir,
            )
            logger.info(f"Created browser with persistent context at: {self.user_data_dir}")
            return browser
        except Exception as e:
            logger.warning(f"Error creating browser with persistent context: {e}")
            logger.info("Falling back to default browser (no persistence)")
            # Fallback to default browser
            return Browser(headless=headless)
