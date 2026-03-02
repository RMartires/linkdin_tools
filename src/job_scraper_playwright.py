"""LinkedIn job scraper using Playwright"""

import os
import re
import asyncio
import time
from typing import List, Optional
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime
from dotenv import load_dotenv

from src.models import JobListing
from src.session_manager import SessionManager
from src.utils.logger import logger

load_dotenv()


class JobScraperPlaywright:
    """Scrape LinkedIn jobs using Playwright"""
    
    def __init__(self, model: Optional[str] = None, browser=None, playwright_browser=None, headless: bool = False):
        """Initialize job scraper
        
        Args:
            model: Optional model name override (kept for backward compatibility)
            browser: Optional browser-use Browser instance (backward compatibility)
            playwright_browser: Optional Playwright Browser instance
            headless: Whether to run browser in headless mode (default: False)
        """
        self.model = model  # Kept for backward compatibility but not used
        self.browser = browser  # Kept for backward compatibility
        self.playwright_browser = playwright_browser
        self.session_manager = SessionManager()
        self.page = None
        self.headless = headless
    
    def _extract_job_id(self, url: str) -> Optional[str]:
        """Extract job ID from LinkedIn URL"""
        try:
            # LinkedIn job URLs typically have format: linkedin.com/jobs/view/{job_id}
            match = re.search(r'/jobs/view/(\d+)', url)
            if match:
                return match.group(1)
            # Alternative format: linkedin.com/jobs/collections/{collection_id}/?currentJobId={job_id}
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            if 'currentJobId' in query_params:
                return query_params['currentJobId'][0]
            return None
        except Exception as e:
            logger.warning(f"Could not extract job ID from URL {url}: {e}")
            return None
    
    async def _get_page(self, headless: Optional[bool] = None):
        """Get or create a Playwright page
        
        Args:
            headless: Override headless mode (uses self.headless if None)
        """
        if self.page and not self.page.is_closed():
            return self.page
        
        # Use instance headless if not overridden
        if headless is None:
            headless = self.headless
        
        # Get browser (launched with LinkedIn cookies via storage_state)
        if not self.playwright_browser:
            self.playwright_browser = await self.session_manager.get_playwright_browser(headless=headless)
        
        # Get the context with LinkedIn cookies and a page
        contexts = self.playwright_browser.contexts
        if contexts:
            context = contexts[0]
            pages = context.pages
            if pages:
                self.page = pages[0]
            else:
                self.page = await context.new_page()
        else:
            context = await self.playwright_browser.new_context()
            self.page = await context.new_page()
        
        # Auto-dismiss any JavaScript dialogs
        self.page.on("dialog", lambda dialog: dialog.dismiss())
        
        return self.page
    
    async def _navigate_to_jobs_page(self, page):
        """Navigate to LinkedIn Jobs page"""
        logger.info("Navigating to LinkedIn Jobs page...")
        await page.goto("https://www.linkedin.com/jobs", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)  # Wait for page to fully load
        
        # Wait for search input to be visible (ensures page is fully loaded)
        try:
            # Try to wait for new UI input first
            await page.wait_for_selector('input[componentkey="semanticSearchBox"], input[placeholder*="Describe the job you want"]', timeout=5000, state="visible")
            logger.debug("New LinkedIn UI search input detected")
        except:
            # Fallback: wait for any search input
            try:
                await page.wait_for_selector('input[data-testid="typeahead-input"]', timeout=5000, state="visible")
                logger.debug("Search input detected (may be old UI)")
            except:
                logger.warning("Search input not immediately visible, continuing anyway")
        
        logger.info("Successfully navigated to LinkedIn Jobs page")
    
    async def _find_title_input(self, page):
        """Find the job search input field (now a single combined field for title and location)"""
        # Priority order: new single input field first, then fallback to old separate fields
        # Try new UI selectors first with longer timeout
        new_ui_selectors = [
            'input[componentkey="semanticSearchBox"]',
            'input[data-testid="typeahead-input"][componentkey="semanticSearchBox"]',
            'input[placeholder*="Describe the job you want"]',
        ]
        
        # Try new UI first with longer timeout
        for selector in new_ui_selectors:
            try:
                title_input = await page.wait_for_selector(selector, timeout=5000, state="visible")
                if title_input:
                    placeholder = await title_input.get_attribute('placeholder') or ''
                    componentkey = await title_input.get_attribute('componentkey') or ''
                    logger.info(f"Found NEW UI search input using selector: {selector} (componentkey='{componentkey}', placeholder='{placeholder}')")
                    return title_input
            except:
                continue
        
        # Fallback to old UI selectors (for backward compatibility)
        old_ui_selectors = [
            'input[componentkey="jobSearchBox"]',
            'input[placeholder*="Title, skill or Company"]',
            'input[placeholder*="Title"]',
            'input[data-testid="typeahead-input"][placeholder*="Title"]',
        ]
        
        for selector in old_ui_selectors:
            try:
                title_input = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if title_input:
                    # Verify it's the title field by checking placeholder
                    placeholder = await title_input.get_attribute('placeholder') or ''
                    componentkey = await title_input.get_attribute('componentkey') or ''
                    
                    if ('Title' in placeholder or 
                        'skill' in placeholder.lower() or 
                        'Company' in placeholder):
                        logger.info(f"Found OLD UI search input using selector: {selector} (componentkey='{componentkey}', placeholder='{placeholder}')")
                        return title_input
            except:
                continue
        
        # Fallback: find all typeahead inputs and identify by placeholder or componentkey
        # Prioritize new UI inputs first
        try:
            all_inputs = await page.query_selector_all('input[data-testid="typeahead-input"]')
            
            # First pass: look for new UI inputs
            for input_elem in all_inputs:
                placeholder = await input_elem.get_attribute('placeholder') or ''
                componentkey = await input_elem.get_attribute('componentkey') or ''
                
                if (componentkey == 'semanticSearchBox' or 'Describe the job' in placeholder):
                    logger.info(f"Found NEW UI search input using fallback method (componentkey='{componentkey}', placeholder='{placeholder}')")
                    return input_elem
            
            # Second pass: look for old UI inputs
            for input_elem in all_inputs:
                placeholder = await input_elem.get_attribute('placeholder') or ''
                componentkey = await input_elem.get_attribute('componentkey') or ''
                
                if ('Title' in placeholder or 
                    'skill' in placeholder.lower() or 
                    'Company' in placeholder):
                    logger.info(f"Found OLD UI search input using fallback method (componentkey='{componentkey}', placeholder='{placeholder}')")
                    return input_elem
        except Exception as e:
            logger.debug(f"Fallback method error: {e}")
        
        return None
    
    async def _find_location_input(self, page):
        """Find the location search input field
        
        Note: LinkedIn now uses a single combined input field. This method returns
        the same input as _find_title_input() for backward compatibility.
        """
        # First try to find the new single combined input field
        combined_input = await self._find_title_input(page)
        if combined_input:
            # Check if it's the new semanticSearchBox (single field)
            componentkey = await combined_input.get_attribute('componentkey') or ''
            if componentkey == 'semanticSearchBox':
                logger.debug("Using single combined input field for location (new LinkedIn UI)")
                return combined_input
        
        # Fallback: try to find old separate location field (for backward compatibility)
        location_selectors = [
            'input[placeholder*="City, state, or zip code"]',
            'input[placeholder*="City"]',
            'input[placeholder*="Location"]',
            'input[data-testid="typeahead-input"][placeholder*="City"]',
        ]
        
        for selector in location_selectors:
            try:
                location_input = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if location_input:
                    # Verify it's the location field by checking placeholder
                    placeholder = await location_input.get_attribute('placeholder') or ''
                    if 'City' in placeholder or 'Location' in placeholder or 'zip' in placeholder.lower():
                        logger.debug(f"Found separate location input using selector: {selector}")
                        return location_input
            except:
                continue
        
        # Fallback: find all typeahead inputs and identify by placeholder
        try:
            all_inputs = await page.query_selector_all('input[data-testid="typeahead-input"]')
            for input_elem in all_inputs:
                placeholder = await input_elem.get_attribute('placeholder') or ''
                if 'City' in placeholder or 'Location' in placeholder or 'zip' in placeholder.lower():
                    logger.debug("Found location input using fallback method")
                    return input_elem
        except:
            pass
        
        # If no separate location field found, return the combined input (if found)
        return combined_input
    
    async def _search_jobs(self, page, keywords: str, location: Optional[str] = None):
        """Enter search query in LinkedIn Jobs search
        
        LinkedIn now uses a single combined input field. The format is: "$title in $location"
        For backward compatibility, this method also supports the old separate fields.
        """
        logger.info(f"Searching for jobs: keywords='{keywords}', location='{location}'")
        
        # Find the search input field
        search_input = await self._find_title_input(page)
        if not search_input:
            # Log available inputs for debugging
            try:
                all_inputs = await page.query_selector_all('input[data-testid="typeahead-input"]')
                logger.error(f"Could not find search input. Found {len(all_inputs)} typeahead inputs:")
                for i, inp in enumerate(all_inputs):
                    placeholder = await inp.get_attribute('placeholder') or 'N/A'
                    componentkey = await inp.get_attribute('componentkey') or 'N/A'
                    logger.error(f"  Input {i+1}: placeholder='{placeholder}', componentkey='{componentkey}'")
            except:
                pass
            raise Exception("Could not find LinkedIn job search input field")
        
        # Check if this is the new single combined input field
        componentkey = await search_input.get_attribute('componentkey') or ''
        placeholder = await search_input.get_attribute('placeholder') or ''
        
        # Log what we found for debugging
        logger.debug(f"Found input field - componentkey='{componentkey}', placeholder='{placeholder}'")
        
        # Check for new UI: semanticSearchBox componentkey OR "Describe the job" placeholder
        is_new_ui = (componentkey == 'semanticSearchBox' or 'Describe the job' in placeholder)
        
        if is_new_ui:
            logger.info(f"Detected new LinkedIn UI (componentkey='{componentkey}', placeholder='{placeholder}')")
        else:
            logger.info(f"Detected old LinkedIn UI (componentkey='{componentkey}', placeholder='{placeholder}')")
        
        if is_new_ui:
            # New LinkedIn UI: single combined input field
            # Format: "$title in $location" or just "$title" if no location
            if location:
                search_query = f"{keywords} in {location}"
            else:
                search_query = keywords
            
            logger.info(f"Using new LinkedIn UI - combined search query: '{search_query}'")
            
            # Clear and fill the combined input field
            await search_input.click()
            await asyncio.sleep(0.3)  # Small delay for focus
            
            # Clear existing text - try multiple methods for reliability
            await search_input.fill("")
            await search_input.press("Control+A")  # Select all as backup
            await asyncio.sleep(0.2)
            
            # Type the combined query
            await search_input.type(search_query, delay=50)  # Type with delay to mimic human behavior
            await asyncio.sleep(0.5)  # Wait for any autocomplete to appear
            
            # Submit search by pressing Enter
            await search_input.press("Enter")
        else:
            # Old LinkedIn UI: separate title and location fields (backward compatibility)
            logger.info("Using old LinkedIn UI - separate title and location fields")
            
            # Enter keywords in title field
            await search_input.click()
            await asyncio.sleep(0.3)  # Small delay for focus
            await search_input.fill("")  # Clear any existing text
            await search_input.type(keywords, delay=50)  # Type with delay to mimic human behavior
            await asyncio.sleep(0.5)  # Wait for any autocomplete to appear
            
            # If location is provided, find and fill location field
            if location:
                location_input = await self._find_location_input(page)
                if not location_input or location_input == search_input:
                    # If location_input is same as search_input, it means we're using new UI
                    # This shouldn't happen in old UI, but handle it gracefully
                    logger.warning(f"Could not find separate location input field. Continuing search without location filter.")
                    await search_input.press("Enter")
                else:
                    # Enter location in separate location field
                    await location_input.click()
                    await asyncio.sleep(0.3)  # Small delay for focus
                    await location_input.fill("")  # Clear any existing text
                    await location_input.type(location, delay=50)
                    await asyncio.sleep(0.5)  # Wait for any autocomplete to appear
                    
                    # Submit search by pressing Enter on location field
                    await location_input.press("Enter")
            else:
                # Submit search by pressing Enter on title field
                await search_input.press("Enter")
        
        logger.info("Search submitted, waiting for navigation and results to load...")
        
        # Wait for navigation to complete (URL change or page load)
        try:
            # Wait for URL to change to results page (contains /jobs/search or /jobs/)
            await page.wait_for_function(
                '() => window.location.href.includes("/jobs/search") || window.location.href.includes("/jobs/")',
                timeout=15000
            )
            current_url = page.url
            logger.info(f"Navigation completed. Current URL: {current_url}")
        except Exception as e:
            logger.warning(f"URL didn't change as expected: {e}. Current URL: {page.url}")
            # Continue anyway - maybe results load on same page
        
        # Wait for network to be idle (all resources loaded)
        try:
            logger.info("Waiting for network to be idle...")
            await page.wait_for_load_state("networkidle", timeout=10000)
        except:
            logger.debug("Network idle timeout - continuing anyway")
        
        # Wait for job results to actually appear on the page
        logger.info("Waiting for job results to appear on page...")
        job_results_found = False
        max_wait_time = 30  # seconds - increased timeout
        start_time = time.time()
        
        while (time.time() - start_time) < max_wait_time:
            try:
                # First, check using evaluate (runs in browser context - more reliable)
                # Check for both new UI and old UI structures
                job_count = await page.evaluate('''
                    () => {
                        const newUI = document.querySelectorAll('[data-view-name="job-search-job-card"]').length;
                        const oldUI = document.querySelectorAll('[data-job-id]').length;
                        return newUI > 0 ? newUI : oldUI;
                    }
                ''')
                
                if job_count > 0:
                    logger.info(f"Found {job_count} job cards using browser context evaluation!")
                    job_results_found = True
                    break
                
                # Also check using Playwright selectors (both new and old UI)
                job_indicators = [
                    'div[data-view-name="job-search-job-card"]',  # New UI
                    '[data-job-id]',  # Old UI
                    '.job-card-container',  # Old UI
                    'li[data-occludable-job-id]',  # Old UI
                    '[class*="job-card"]',  # Old UI fallback
                    '[class*="jobs-search-results"]',  # Old UI fallback
                ]
                
                for indicator in job_indicators:
                    try:
                        elements = await page.query_selector_all(indicator)
                        if len(elements) > 0:
                            logger.debug(f"Found {len(elements)} elements matching '{indicator}' - results page loaded!")
                            job_results_found = True
                            break
                    except:
                        continue
                
                if job_results_found:
                    break
                
                # Check if elements are in iframes
                frames = page.frames
                if len(frames) > 1:  # More than just main frame
                    logger.debug(f"Found {len(frames)} frames - checking iframes for job cards...")
                    for i, frame in enumerate(frames):
                        try:
                            # Check for both new UI and old UI
                            iframe_job_count = await frame.evaluate('''
                                () => {
                                    const newUI = document.querySelectorAll('[data-view-name="job-search-job-card"]').length;
                                    const oldUI = document.querySelectorAll('[data-job-id]').length;
                                    return newUI > 0 ? newUI : oldUI;
                                }
                            ''')
                            if iframe_job_count > 0:
                                logger.info(f"Found {iframe_job_count} job cards in frame {i}!")
                                job_results_found = True
                                break
                        except:
                            continue
                
                if job_results_found:
                    break
                    
                await asyncio.sleep(1)  # Check every second
            except Exception as e:
                logger.debug(f"Error checking for job results: {e}")
                await asyncio.sleep(1)
        
        if not job_results_found:
            logger.error("Job results did not appear on page after waiting!")
            # Log current page state for debugging
            try:
                current_url = page.url
                page_title = await page.title()
                logger.error(f"Current URL: {current_url}")
                logger.error(f"Page title: {page_title}")
            except:
                pass
        else:
            logger.info("Job results page successfully loaded")
        
        await asyncio.sleep(2)  # Additional wait for any animations/rendering
    
    async def _apply_date_filter(self, page):
        """Apply date filter to show jobs from past 24 hours by adding query parameter to URL"""
        logger.info("Applying date filter: Past 24 hours")
        
        try:
            # Get current URL
            current_url = page.url
            logger.debug(f"Current URL: {current_url}")
            
            # Parse URL and add/update the f_TPR parameter
            parsed = urlparse(current_url)
            query_params = parse_qs(parsed.query)
            
            # Add or update the f_TPR parameter to r86400 (Past 24 hours)
            query_params['f_TPR'] = ['r86400']
            
            # Reconstruct the URL with the new query parameter
            new_query = urlencode(query_params, doseq=True)
            new_url = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment
            ))
            
            logger.info(f"Navigating to URL with date filter: {new_url}")
            
            # Navigate to the new URL
            await page.goto(new_url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # Wait for page to load
            
            # Wait for job results to appear
            logger.info("Waiting for filtered results to load...")
            job_results_found = False
            max_wait_time = 15
            start_time = time.time()
            
            while (time.time() - start_time) < max_wait_time:
                try:
                    # Check for both new UI and old UI
                    job_count = await page.evaluate('''
                        () => {
                            const newUI = document.querySelectorAll('[data-view-name="job-search-job-card"]').length;
                            const oldUI = document.querySelectorAll('[data-job-id]').length;
                            return newUI > 0 ? newUI : oldUI;
                        }
                    ''')
                    if job_count > 0:
                        logger.info(f"Found {job_count} job cards after applying date filter")
                        job_results_found = True
                        break
                    await asyncio.sleep(1)
                except:
                    await asyncio.sleep(1)
            
            if job_results_found:
                logger.info("✓ Date filter (Past 24 hours) applied successfully via URL parameter")
            else:
                logger.warning("Date filter applied but job results not detected")
                
        except Exception as e:
            logger.warning(f"Could not apply date filter: {e}. Continuing without date filter...", exc_info=True)
    
    async def _apply_filters(self, page, experience_level: Optional[str] = None, job_type: Optional[str] = None):
        """Apply experience level and job type filters if provided"""
        if not experience_level and not job_type:
            return
        
        logger.info(f"Applying filters: experience_level={experience_level}, job_type={job_type}")
        
        # Look for filter buttons/sections
        # This is a simplified implementation - LinkedIn's filter UI may vary
        try:
            # Wait for filters to be available
            await asyncio.sleep(2)
            
            # Experience level filter
            if experience_level:
                # Try to find and click experience level filter
                # Selectors may need adjustment based on LinkedIn's actual UI
                exp_selectors = [
                    f'button:has-text("{experience_level}")',
                    f'[aria-label*="{experience_level}"]',
                ]
                for selector in exp_selectors:
                    try:
                        element = await page.wait_for_selector(selector, timeout=3000)
                        if element:
                            await element.click()
                            await asyncio.sleep(1)
                            break
                    except:
                        continue
            
            # Job type filter
            if job_type:
                # Similar approach for job type
                type_selectors = [
                    f'button:has-text("{job_type}")',
                    f'[aria-label*="{job_type}"]',
                ]
                for selector in type_selectors:
                    try:
                        element = await page.wait_for_selector(selector, timeout=3000)
                        if element:
                            await element.click()
                            await asyncio.sleep(1)
                            break
                    except:
                        continue
            
            # Wait for filtered results
            await asyncio.sleep(2)
            logger.info("Filters applied")
        except Exception as e:
            logger.warning(f"Could not apply filters: {e}. Continuing without filters...")
    
    async def _find_job_list_container(self, page):
        """Find the job list container using stable semantic selectors
        
        LinkedIn now uses a div-based structure instead of ul/li:
        - Main container: div[componentkey="SearchResultsMainContent"] or div[data-testid="lazy-column"]
        - Job cards: div[data-view-name="job-search-job-card"]
        """
        # Priority selectors for new LinkedIn UI (div-based)
        new_ui_selectors = [
            'div[componentkey="SearchResultsMainContent"]',  # Main container with componentkey
            'div[data-testid="lazy-column"][componentkey="SearchResultsMainContent"]',  # More specific
            'div[data-testid="lazy-column"]',  # Fallback to data-testid
            'div[data-component-type="LazyColumn"]',  # Alternative attribute
        ]
        
        logger.info("Attempting to find job list container...")
        
        # Try new UI selectors first
        for selector in new_ui_selectors:
            try:
                logger.debug(f"Trying new UI selector: {selector}")
                list_container = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if list_container:
                    logger.info(f"Found NEW UI job list container using selector: {selector}")
                    return list_container
            except Exception as e:
                logger.debug(f"New UI selector '{selector}' failed: {e}")
                continue
        
        # Fallback to old UI selectors (ul-based structure for backward compatibility)
        old_ui_selectors = [
            '.scaffold-layout__list > ul',  # Direct child ul of scaffold-layout__list (double underscore)
            '.scaffold-layout__list ul',  # Descendant ul (more flexible)
            '.scaffold-layout_list > ul',  # Single underscore variant
            '.scaffold-layout_list ul',  # Single underscore variant descendant
            'ul[class*="scaffold-layout"]',  # Fallback: any ul with scaffold-layout in class
            'ul.scaffold-layout__list-container',  # Alternative stable class
            '.scaffold-layout__list',  # Try the parent div itself (double underscore)
            '.scaffold-layout_list',  # Try the parent div itself (single underscore)
        ]
        
        for selector in old_ui_selectors:
            try:
                logger.debug(f"Trying old UI selector: {selector}")
                list_container = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if list_container:
                    logger.info(f"Found OLD UI job list container using selector: {selector}")
                    return list_container
            except Exception as e:
                logger.debug(f"Old UI selector '{selector}' failed: {e}")
                continue
        
        # Debug: Log what's actually on the page (only if all selectors fail)
        logger.warning("Could not find job list container with specific selectors.")
        try:
            # Quick check for job cards using browser context
            job_count_browser = await page.evaluate('document.querySelectorAll("[data-view-name=\\"job-search-job-card\\"]").length')
            logger.debug(f"Browser context check: Found {job_count_browser} elements with [data-view-name='job-search-job-card']")
            
            # Check for new UI container
            new_container_count = await page.evaluate('document.querySelectorAll("[componentkey=\\"SearchResultsMainContent\\"]").length')
            logger.debug(f"Found {new_container_count} elements with componentkey='SearchResultsMainContent'")
            
            # Check for old UI ul elements
            all_uls = await page.query_selector_all('ul')
            logger.debug(f"Found {len(all_uls)} <ul> elements on the page")
            
        except Exception as e:
            logger.debug(f"Error during debugging: {e}")
        
        return None
    
    async def _find_target_frame(self, page):
        """Find the frame that contains job cards (supports both new and old UI)"""
        frames = page.frames
        for i, frame in enumerate(frames):
            try:
                # Check for both new UI and old UI structures
                job_count = await frame.evaluate('''
                    () => {
                        const newUI = document.querySelectorAll('[data-view-name="job-search-job-card"]').length;
                        const oldUI = document.querySelectorAll('[data-job-id]').length;
                        return newUI > 0 ? newUI : oldUI;
                    }
                ''')
                if job_count > 0:
                    logger.debug(f"Found {job_count} job cards in frame {i}")
                    return frame
            except:
                continue
        return None
    
    async def _get_job_ids(self, page):
        """Extract unique job IDs from visible job cards
        
        Supports both new UI (div-based) and old UI (li-based) structures
        """
        job_ids = set()
        
        # First, try to find the frame with job cards
        target_frame = await self._find_target_frame(page)
        extraction_page = target_frame if target_frame else page
        
        # Try new UI structure first: div[data-view-name="job-search-job-card"]
        try:
            new_ui_cards = await extraction_page.query_selector_all('div[data-view-name="job-search-job-card"]')
            if new_ui_cards:
                logger.debug(f"Found {len(new_ui_cards)} job cards using NEW UI structure (div[data-view-name='job-search-job-card'])")
                
                for card in new_ui_cards:
                    # Extract job ID from href links containing /jobs/view/
                    try:
                        # Look for links with /jobs/view/ in href
                        links = await card.query_selector_all('a[href*="/jobs/view/"]')
                        for link in links:
                            href = await link.get_attribute('href')
                            if href:
                                # Extract job ID from URL: /jobs/view/{job_id}/
                                match = re.search(r'/jobs/view/(\d+)', href)
                                if match:
                                    job_id = match.group(1)
                                    job_ids.add(job_id)
                                    logger.debug(f"Extracted job ID {job_id} from link href")
                    except Exception as e:
                        logger.debug(f"Error extracting job ID from new UI card: {e}")
                        pass
                
                if job_ids:
                    logger.debug(f"Extracted {len(job_ids)} job IDs from new UI structure")
                    return job_ids
        except Exception as e:
            logger.debug(f"Error finding new UI job cards: {e}")
        
        # Fallback to old UI structure: li elements
        try:
            # Get all list items - try multiple selectors (including single/double underscore variants)
            list_item_selectors = [
                'li.scaffold-layout__list-item',  # Double underscore
                'li.scaffold-layout_list-item',  # Single underscore variant
                'li[data-occludable-job-id]',  # By data attribute
                'li[class*="scaffold-layout__list-item"]',  # Double underscore partial match
                'li[class*="scaffold-layout_list-item"]',  # Single underscore partial match
            ]
            
            list_items = []
            for selector in list_item_selectors:
                try:
                    items = await extraction_page.query_selector_all(selector)
                    if items:
                        logger.debug(f"Found {len(items)} list items using OLD UI selector: {selector}")
                        list_items = items
                        break
                except:
                    continue
            
            if not list_items:
                logger.debug(f"No list items found with standard selectors. Trying fallback...")
                # Try to find any li elements
                all_lis = await extraction_page.query_selector_all('li')
                logger.debug(f"Found {len(all_lis)} total <li> elements on page")
                list_items = all_lis
            
            logger.debug(f"Processing {len(list_items)} list items for job IDs (OLD UI)")
            
            for item in list_items:
                # Try data-job-id first (on the card container inside li)
                try:
                    card = await item.query_selector('[data-job-id]')
                    if card:
                        job_id = await card.get_attribute('data-job-id')
                        if job_id:
                            job_ids.add(job_id)
                            continue
                except:
                    pass
                
                # Fallback to data-occludable-job-id on the li element
                try:
                    occludable_id = await item.get_attribute('data-occludable-job-id')
                    if occludable_id:
                        job_ids.add(occludable_id)
                except:
                    pass
        except Exception as e:
            logger.warning(f"Error extracting job IDs: {e}", exc_info=True)
        
        logger.debug(f"Extracted {len(job_ids)} unique job IDs")
        return job_ids
    
    async def _is_valid_job_card(self, card_element):
        """Check if a card element contains a valid job card (not a placeholder)
        
        Supports both new UI (div[data-view-name="job-search-job-card"]) and old UI (li with data-job-id)
        """
        try:
            # Check for new UI structure first
            view_name = await card_element.get_attribute('data-view-name')
            if view_name == 'job-search-job-card':
                # For new UI, if it has data-view-name="job-search-job-card", it's valid
                # The link might be nested deeper or loaded dynamically, so we'll trust the attribute
                # But also try to verify by checking for the clickable button or any links
                has_button = await card_element.query_selector('div[role="button"]')
                if has_button:
                    logger.debug("New UI card validated: has role='button'")
                    return True
                
                # Also check for links as secondary validation
                link = await card_element.query_selector('a[href*="/jobs/view/"]')
                if link:
                    return True
                
                # Check all links
                all_links = await card_element.query_selector_all('a')
                for link in all_links:
                    href = await link.get_attribute('href')
                    if href and '/jobs/view/' in href:
                        return True
                
                # If it has the data-view-name attribute, consider it valid even without link
                # (link might be in nested structure or loaded dynamically)
                logger.debug(f"New UI card validated by data-view-name attribute (found {len(all_links)} total links)")
                return True  # Changed from False to True - trust the attribute
            
            # Check for old UI structure
            card = await card_element.query_selector('[data-job-id]')
            if card:
                # Check if it has actual content (title link)
                title_link = await card.query_selector('a.job-card-container__link')
                return title_link is not None
            
            # Also check if it's an li element with data-occludable-job-id
            occludable_id = await card_element.get_attribute('data-occludable-job-id')
            if occludable_id:
                return True
            
            return False
        except Exception as e:
            logger.debug(f"Error checking if card is valid: {e}")
            return False
    
    async def _scroll_job_list(self, page, max_results: int):
        """Scroll through job list to load more jobs using correct selectors"""
        logger.info(f"Scrolling job list to load at least {max_results} jobs...")
        
        # Find the frame that contains job cards
        target_frame = await self._find_target_frame(page)
        if target_frame:
            logger.info("Using iframe for scrolling job list")
            scroll_page = target_frame
        else:
            logger.info("Using main page for scrolling job list")
            scroll_page = page
        
        # Find the job list container
        job_list_container = await self._find_job_list_container(scroll_page)
        
        if not job_list_container:
            logger.warning("Could not find job list container, falling back to page scroll")
            job_list_container = scroll_page
        
        # Track unique job IDs to detect when new jobs load
        previous_job_ids = set()
        scroll_attempts = 0
        max_scroll_attempts = 50
        no_progress_count = 0
        max_no_progress = 3
        
        while scroll_attempts < max_scroll_attempts:
            # Get current job IDs (this method now handles frames internally)
            current_job_ids = await self._get_job_ids(page)
            current_count = len(current_job_ids)
            
            logger.debug(f"Found {current_count} unique job IDs (target: {max_results})")
            
            if current_count >= max_results:
                logger.info(f"Found {current_count} jobs, target reached")
                break
            
            # Check if we made progress
            new_jobs = current_job_ids - previous_job_ids
            if new_jobs:
                logger.debug(f"Loaded {len(new_jobs)} new jobs")
                scroll_attempts = 0
                no_progress_count = 0
            else:
                no_progress_count += 1
                if no_progress_count >= max_no_progress:
                    logger.info("No new jobs loaded after multiple scroll attempts")
                    break
            
            # Get the last visible job card to scroll to
            try:
                # Try new UI first (div-based)
                new_ui_cards = await scroll_page.query_selector_all('div[data-view-name="job-search-job-card"]')
                if new_ui_cards:
                    logger.debug(f"Found {len(new_ui_cards)} NEW UI cards for scrolling")
                    valid_cards = []
                    for card in new_ui_cards:
                        if await self._is_valid_job_card(card):
                            valid_cards.append(card)
                else:
                    # Fallback to old UI (li-based)
                    list_item_selectors = [
                        'li.scaffold-layout__list-item',
                        'li.scaffold-layout_list-item',
                        'li[data-occludable-job-id]',
                    ]
                    list_items = []
                    for selector in list_item_selectors:
                        try:
                            items = await scroll_page.query_selector_all(selector)
                            if items:
                                list_items = items
                                break
                        except:
                            continue
                    
                    valid_cards = []
                    for item in list_items:
                        if await self._is_valid_job_card(item):
                            valid_cards.append(item)
                
                if valid_cards:
                    # Scroll the last valid card into view to trigger lazy loading
                    last_card = valid_cards[-1]
                    await last_card.scroll_into_view_if_needed()
                    await asyncio.sleep(1.5)  # Wait for lazy loading
                else:
                    # Fallback: scroll the list container
                    if job_list_container != scroll_page:
                        await job_list_container.evaluate('''
                            element => {
                                element.scrollTop += 800;
                            }
                        ''')
                    else:
                        await scroll_page.evaluate('window.scrollBy(0, 800)')
                    await asyncio.sleep(1.5)
            except Exception as e:
                logger.debug(f"Error during scroll: {e}")
                # Fallback scroll
                if job_list_container != scroll_page:
                    await job_list_container.evaluate('''
                        element => {
                            element.scrollTop += 800;
                        }
                    ''')
                else:
                    await scroll_page.evaluate('window.scrollBy(0, 800)')
                await asyncio.sleep(1.5)
            
            previous_job_ids = current_job_ids
            scroll_attempts += 1
            
            # Small delay to mimic human behavior
            await asyncio.sleep(0.5)
        
        # Final count
        final_job_ids = await self._get_job_ids(page)
        logger.info(f"Finished scrolling. Found {len(final_job_ids)} unique job cards")
    
    async def _extract_job_card(self, card_element) -> Optional[dict]:
        """Extract job data from a single job card element
        
        Supports both new UI (div[data-view-name="job-search-job-card"]) and old UI (li.scaffold-layout__list-item)
        """
        try:
            # Check if this is new UI structure
            view_name = await card_element.get_attribute('data-view-name')
            is_new_ui = view_name == 'job-search-job-card'
            logger.info(f"Extracting job card - is_new_ui: {is_new_ui}, view_name: {view_name}")
            
            if is_new_ui:
                # New UI: Extract from div[data-view-name="job-search-job-card"]
                card_container = card_element
                
                # Extract job ID from link href - try multiple strategies
                job_id = None
                job_url = None
                title = None
                
                # Strategy 1: Find link with /jobs/view/ in href
                title_link = await card_container.query_selector('a[href*="/jobs/view/"]')
                logger.info(f"Strategy 1 - Found link with selector 'a[href*=\"/jobs/view/\"]': {title_link is not None}")
                if not title_link:
                    # Strategy 2: Try finding any link in the card
                    all_links = await card_container.query_selector_all('a')
                    logger.debug(f"Strategy 2 - Found {len(all_links)} total links in card")
                    for link in all_links:
                        href = await link.get_attribute('href')
                        if href and '/jobs/view/' in href:
                            title_link = link
                            logger.debug(f"Strategy 2 - Found job link: {href}")
                            break
                
                if title_link:
                    href = await title_link.get_attribute('href')
                    if href:
                        # Extract job ID from URL: /jobs/view/{job_id}/
                        match = re.search(r'/jobs/view/(\d+)', href)
                        if match:
                            job_id = match.group(1)
                            logger.debug(f"Extracted job ID {job_id} from href: {href}")
                        else:
                            logger.warning(f"Could not extract job ID from href: {href}")
                        
                        # Get URL (clean it)
                        if '?' in href:
                            href = href.split('?')[0]
                        if href.startswith('/'):
                            job_url = f"https://www.linkedin.com{href}"
                        elif href.startswith('http'):
                            job_url = href
                        else:
                            job_url = f"https://www.linkedin.com/{href}"
                    else:
                        logger.debug("Link found but href attribute is empty")
                else:
                    logger.warning("Could not find job link with primary selector - trying alternative methods...")
                    # Try to find job ID from any link in the card
                    all_links = await card_container.query_selector_all('a')
                    logger.debug(f"Found {len(all_links)} total links in card, checking for job links...")
                    for link in all_links:
                        href = await link.get_attribute('href')
                        if href and '/jobs/view/' in href:
                            match = re.search(r'/jobs/view/(\d+)', href)
                            if match:
                                job_id = match.group(1)
                                logger.debug(f"Found job ID {job_id} from alternative link: {href}")
                                if not job_url:
                                    if '?' in href:
                                        href = href.split('?')[0]
                                    if href.startswith('/'):
                                        job_url = f"https://www.linkedin.com{href}"
                                    elif href.startswith('http'):
                                        job_url = href
                                    else:
                                        job_url = f"https://www.linkedin.com/{href}"
                                # Also set title_link if this link looks like a title link
                                if not title_link:
                                    link_text = await link.inner_text()
                                    if link_text and len(link_text.strip()) > 5:
                                        title_link = link
                                        logger.debug(f"Using alternative link as title_link: {link_text[:50]}")
                                break
                    
                    # Debug: Log card HTML structure if still no job_id
                    if not job_id:
                        try:
                            card_html = await card_container.inner_html()
                            logger.debug(f"Card HTML (first 500 chars): {card_html[:500]}")
                        except:
                            pass
                        # Try to extract from tracking data or other attributes
                        componentkey = await card_container.get_attribute('componentkey')
                        if componentkey:
                            logger.debug(f"Found componentkey: {componentkey} (but cannot extract job ID from it)")
                
                # Fallback: Try browser evaluation to extract job ID directly from DOM
                if not job_id:
                    logger.info("Primary extraction failed, trying browser evaluation fallback...")
                    try:
                        eval_result = await card_container.evaluate('''(element) => {
                            const links = element.querySelectorAll('a');
                            for (let link of links) {
                                const href = link.getAttribute('href');
                                if (href && href.includes('/jobs/view/')) {
                                    const match = href.match(/\\/jobs\\/view\\/(\\d+)/);
                                    if (match) {
                                        return {
                                            job_id: match[1],
                                            href: href,
                                            title: link.innerText.trim() || link.textContent.trim()
                                        };
                                    }
                                }
                            }
                            return null;
                        }''')
                        if eval_result and eval_result.get('job_id'):
                            job_id = eval_result['job_id']
                            if not job_url:
                                href = eval_result['href']
                                if '?' in href:
                                    href = href.split('?')[0]
                                if href.startswith('/'):
                                    job_url = f"https://www.linkedin.com{href}"
                                elif href.startswith('http'):
                                    job_url = href
                                else:
                                    job_url = f"https://www.linkedin.com/{href}"
                            if not title and eval_result.get('title'):
                                title = eval_result['title'].strip()
                            logger.info(f"✓ Fallback extraction successful: job_id={job_id}, title={title}")
                    except Exception as e:
                        logger.debug(f"Browser evaluation fallback failed: {e}")
                
                if not job_id:
                    logger.error(f"Could not extract job ID from new UI card (found link: {title_link is not None}, job_url: {job_url})")
                    return None
                
                # Extract title from link or span (try multiple methods)
                if title_link:
                    title_text = await title_link.inner_text()
                    if not title_text or title_text.strip() == '':
                        # Try getting from span with class _48b902c5 (visible text)
                        title_span = await card_container.query_selector('span._48b902c5')
                        if title_span:
                            title_text = await title_span.inner_text()
                            logger.debug(f"Extracted title from span._48b902c5: {title_text}")
                    
                    if title_text:
                        title = title_text.strip()
                        # Remove "(Verified job)" suffix if present
                        title = re.sub(r'\s*\(Verified job\)\s*', '', title)
                        logger.debug(f"Extracted title: {title}")
                else:
                    # Try to get title from other sources
                    logger.debug("No title link found, trying alternative title extraction...")
                    title_span = await card_container.query_selector('span._48b902c5')
                    if title_span:
                        title_text = await title_span.inner_text()
                        if title_text:
                            title = title_text.strip()
                            logger.debug(f"Extracted title from span._48b902c5 (no link): {title}")
                    
                    # Also try getting from any link text
                    if not title:
                        all_links = await card_container.query_selector_all('a')
                        for link in all_links:
                            link_text = await link.inner_text()
                            if link_text and link_text.strip() and len(link_text.strip()) > 5:
                                # Likely a job title if it's substantial text
                                title = link_text.strip()
                                logger.debug(f"Extracted title from link text: {title}")
                                break
                
                # If we still don't have title, use fallback (we have job_id so we can continue)
                if not title:
                    logger.warning(f"Could not extract job title from new UI card (job_id: {job_id}), using fallback...")
                    title = f"Job {job_id}"  # Fallback title
            else:
                # Old UI: Extract from li with data-job-id
                card_container = await card_element.query_selector('[data-job-id]')
                if not card_container:
                    # If no card container found, this might be a placeholder
                    return None
                
                # Extract job ID directly from data-job-id attribute
                job_id = await card_container.get_attribute('data-job-id')
                
                # Extract job title and URL
                title_selectors = [
                    'a.job-card-container__link.job-card-list__title--link',  # Most specific
                    'a.job-card-container__link',  # Fallback
                    'a[href*="/jobs/view/"]',  # By href pattern
                ]
                title = None
                job_url = None
                
                for selector in title_selectors:
                    try:
                        title_elem = await card_container.query_selector(selector)
                        if title_elem:
                            # Get title text - handle verified badges by getting text from span
                            title_text = await title_elem.inner_text()
                            if not title_text or title_text.strip() == '':
                                # Try getting from aria-label as fallback
                                title_text = await title_elem.get_attribute('aria-label') or ''
                            
                            if title_text:
                                title = title_text.strip()
                                # Get URL from href
                                href = await title_elem.get_attribute('href')
                                if href:
                                    # Extract base URL (remove query parameters for cleaner URL)
                                    if '?' in href:
                                        href = href.split('?')[0]
                                    if href.startswith('/'):
                                        job_url = f"https://www.linkedin.com{href}"
                                    else:
                                        job_url = href
                            break
                    except:
                        continue
                
                if not title:
                    logger.debug("Could not extract job title")
                    return None
            
            if not job_id:
                logger.debug(f"Could not extract job ID for job: {title}")
                return None
            
            # Extract company name and location
            company = None
            location = None
            
            if is_new_ui:
                # New UI: Company and location are in <p> tags within the card
                # Structure: Company is in a <p> tag, location is in another <p> tag after it
                # Look for p tags that contain company/location info
                try:
                    # Find all p tags in the card
                    p_tags = await card_container.query_selector_all('p')
                    for p in p_tags:
                        text = await p.inner_text()
                        if text and text.strip():
                            text = text.strip()
                            # Company usually comes first and is shorter, location often has "(On-site)" or similar
                            if not company and len(text) < 100 and not '(' in text:
                                # Likely company name
                                company = text
                            elif not location and ('(' in text or 'On-site' in text or 'Remote' in text or ',' in text):
                                # Likely location (contains location indicators)
                                location = text
                            elif not company and company is None:
                                # Fallback: first non-empty p tag might be company
                                company = text
                except Exception as e:
                    logger.debug(f"Error extracting company/location from new UI: {e}")
            else:
                # Old UI: Use existing selectors
                company_selectors = [
                    '.artdeco-entity-lockup__subtitle span',  # Actual structure
                    '.artdeco-entity-lockup__subtitle',  # Fallback
                ]
                
                for selector in company_selectors:
                    try:
                        company_elem = await card_container.query_selector(selector)
                        if company_elem:
                            company_text = await company_elem.inner_text()
                            if company_text and company_text.strip():
                                company = company_text.strip()
                                break
                    except:
                        continue
                
                # Extract location (old UI)
                location_selectors = [
                    '.job-card-container__metadata-wrapper li span',  # Actual structure
                    '.job-card-container__metadata-wrapper span',  # Fallback
                    '.job-card-container__metadata-wrapper li',  # Another fallback
                ]
                
                for selector in location_selectors:
                    try:
                        location_elem = await card_container.query_selector(selector)
                        if location_elem:
                            location_text = await location_elem.inner_text()
                            if location_text:
                                location_text = location_text.strip()
                                # Filter out date-like text
                                if location_text and 'ago' not in location_text.lower() and 'day' not in location_text.lower() and 'hour' not in location_text.lower():
                                    location = location_text
                                    break
                    except:
                        continue
            
            # Extract posted date (works for both new and old UI)
            posted_date = None
            
            if is_new_ui:
                # New UI: Look for text like "1 hour ago", "Posted on March 2, 2026"
                try:
                    # Look for span with aria-hidden="true" that contains time text
                    time_spans = await card_container.query_selector_all('span[aria-hidden="true"]')
                    for span in time_spans:
                        text = await span.inner_text()
                        if text and ('ago' in text.lower() or 'hour' in text.lower() or 'day' in text.lower() or 'Posted on' in text):
                            posted_date = text.strip()
                            break
                except:
                    pass
            
            # Try standard date selectors (works for both UIs)
            date_selectors = [
                'time[datetime]',  # Most reliable - has datetime attribute
                '.job-card-container__footer-item time',  # Old UI
                'time',  # Fallback
            ]
            
            for selector in date_selectors:
                try:
                    date_elem = await card_container.query_selector(selector)
                    if date_elem:
                        # Try datetime attribute first (more reliable)
                        datetime_attr = await date_elem.get_attribute('datetime')
                        if datetime_attr:
                            posted_date = datetime_attr.strip()
                            break
                        # Fallback to inner text
                        date_text = await date_elem.inner_text()
                        if date_text:
                            posted_date = date_text.strip()
                            break
                except:
                    continue
            
            # If no URL found, try to get it from any link in the card
            if not job_url:
                try:
                    link = await card_container.query_selector('a[href*="/jobs/view/"]')
                    if link:
                        href = await link.get_attribute('href')
                        if href:
                            if '?' in href:
                                href = href.split('?')[0]
                            if href.startswith('/'):
                                job_url = f"https://www.linkedin.com{href}"
                            else:
                                job_url = href
                except:
                    pass
            
            # If still no URL but we have job_id, construct it
            if not job_url and job_id:
                job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
            
            return {
                'title': title,
                'company': company.strip() if company else None,
                'location': location,
                'posted_date': posted_date,
                'url': job_url or "https://www.linkedin.com/jobs",
                'job_id': job_id  # Include job_id for easier extraction later
            }
        except Exception as e:
            logger.debug(f"Error extracting job card data: {e}", exc_info=True)
            return None
    
    async def _click_job_card(self, page, list_item, main_page=None) -> bool:
        """Click on a job card to open the details panel
        
        Args:
            page: Playwright page or frame where the card exists (for clicking)
            list_item: The list item element containing the job card
            main_page: Optional main page to check for panel (if clicking in iframe)
            
        Returns:
            True if click was successful and panel loaded, False otherwise
        """
        try:
            # Check if this is new UI or old UI
            view_name = await list_item.get_attribute('data-view-name')
            is_new_ui = view_name == 'job-search-job-card'
            
            # Find the clickable element (title link or card container)
            if is_new_ui:
                # New UI: Click on the div[role="button"] or the link
                clickable_selectors = [
                    'div[role="button"]',  # The main clickable div
                    'a[href*="/jobs/view/"]',  # The job link
                ]
            else:
                # Old UI: Click on title link or card container
                clickable_selectors = [
                    'a.job-card-container__link.job-card-list__title--link',
                    'a.job-card-container__link',
                    'a[href*="/jobs/view/"]',
                    '[data-job-id]',
                ]
            
            clickable_element = None
            for selector in clickable_selectors:
                try:
                    clickable_element = await list_item.query_selector(selector)
                    if clickable_element:
                        break
                except:
                    continue
            
            if not clickable_element:
                logger.debug("Could not find clickable element in job card")
                return False
            
            # Scroll into view if needed
            await clickable_element.scroll_into_view_if_needed()
            await asyncio.sleep(0.5)  # Small delay for scroll animation
            
            # Click the card
            logger.info("Clicking job card to open details panel...")
            await clickable_element.click()
            logger.debug("Clicked job card, waiting for details panel to load...")
            
            # Determine which page to check for the panel
            # If main_page is provided, check there (panel appears on main page even if clicking in iframe)
            # Otherwise check the same page where we clicked
            panel_check_page = main_page if main_page else page
            
            # Wait for the details panel to appear - try multiple strategies
            # The panel might load asynchronously, so we'll check in multiple ways
            panel_found = False
            
            # Strategy 1: Wait for new UI panel selector (data-sdui-screen)
            try:
                logger.debug(f"Waiting for details panel to be attached to DOM (checking {'main page' if main_page else 'current page'})...")
                # Try new UI first
                await panel_check_page.wait_for_selector(
                    'div[role="main"][data-sdui-screen*="SemanticJobDetails"]',
                    state='attached',
                    timeout=3000
                )
                logger.debug("Details panel found in DOM (new UI)")
                panel_found = True
            except Exception as e:
                logger.debug(f"New UI panel not found: {e}, trying old UI...")
                # Fallback to old UI
                try:
                    await panel_check_page.wait_for_selector(
                        '.jobs-search__job-details',
                        state='attached',
                        timeout=1000
                    )
                    logger.debug("Details panel found in DOM (old UI)")
                    panel_found = True
                except:
                    pass
            
            # Strategy 2: Check if panel exists using evaluate (works even if not fully visible)
            if not panel_found:
                try:
                    logger.debug("Checking for panel using browser evaluation...")
                    panel_exists = await panel_check_page.evaluate('''
                        () => {
                            const newPanel = document.querySelector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]');
                            const oldPanel = document.querySelector('.jobs-search__job-details');
                            return (newPanel !== null) || (oldPanel !== null);
                        }
                    ''')
                    if panel_exists:
                        logger.debug("Panel found using browser evaluation")
                        panel_found = True
                except Exception as e:
                    logger.debug(f"Browser evaluation check failed: {e}")
            
            # Strategy 3: Check all frames for the panel (if checking main page)
            if not panel_found and main_page:
                try:
                    logger.debug("Checking all frames for details panel...")
                    frames = main_page.frames if hasattr(main_page, 'frames') else []
                    for i, frame in enumerate(frames):
                        try:
                            panel_in_frame = await frame.evaluate('''
                                () => {
                                    const newPanel = document.querySelector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]');
                                    const oldPanel = document.querySelector('.jobs-search__job-details');
                                    return (newPanel !== null) || (oldPanel !== null);
                                }
                            ''')
                            if panel_in_frame:
                                logger.debug(f"Panel found in frame {i}")
                                panel_found = True
                                break
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"Frame check failed: {e}")
            
            # Strategy 4: Try waiting for visible with longer timeout
            if not panel_found:
                try:
                    logger.debug("Trying to wait for panel to become visible...")
                    # Try new UI first
                    try:
                        await panel_check_page.wait_for_selector(
                            'div[role="main"][data-sdui-screen*="SemanticJobDetails"]',
                            state='visible',
                            timeout=2000
                        )
                        logger.debug("Panel is now visible (new UI)")
                        panel_found = True
                    except:
                        # Fallback to old UI
                        await panel_check_page.wait_for_selector(
                            '.jobs-search__job-details',
                            state='visible',
                            timeout=1000
                        )
                        logger.debug("Panel is now visible (old UI)")
                        panel_found = True
                except Exception as e:
                    logger.debug(f"Panel not visible: {e}")
            
            if panel_found:
                # Additional wait for content to load
                await asyncio.sleep(1.5)
                logger.info("✓ Job details panel loaded successfully")
                return True
            else:
                # Even if we didn't detect it, the user says it's loading, so let's proceed anyway
                logger.warning("Could not detect details panel with standard methods, but proceeding anyway (panel may be loading)")
                await asyncio.sleep(2)  # Give it more time
                return True  # Return True since user confirmed it's working
                
        except Exception as e:
            logger.warning(f"Error clicking job card: {e}")
            return False
    
    async def _extract_company_url_from_details_panel(self, page) -> Optional[str]:
        """Extract company URL from the job details panel
        
        Args:
            page: Playwright page or frame
            
        Returns:
            Company URL string if found, None otherwise
        """
        logger.info("Starting company URL extraction from details panel...")
        try:
            # Try multiple strategies to find the details panel
            details_panel = None
            panel_found = False
            
            # Strategy 1: Try attached state (more lenient) - check both new and old UI
            try:
                logger.debug("Waiting for job details panel to be attached...")
                # Try new UI first
                try:
                    await page.wait_for_selector(
                        'div[role="main"][data-sdui-screen*="SemanticJobDetails"]',
                        state='attached',
                        timeout=2000
                    )
                    details_panel = await page.query_selector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]')
                    if details_panel:
                        logger.info("Job details panel found (attached, new UI)")
                        panel_found = True
                except:
                    # Fallback to old UI
                    await page.wait_for_selector(
                        '.jobs-search__job-details',
                        state='attached',
                        timeout=1000
                    )
                    details_panel = await page.query_selector('.jobs-search__job-details')
                    if details_panel:
                        logger.info("Job details panel found (attached, old UI)")
                        panel_found = True
            except Exception as e:
                logger.debug(f"Panel not found with 'attached' state: {e}")
            
            # Strategy 2: Check using browser evaluation
            if not panel_found:
                try:
                    logger.debug("Checking for panel using browser evaluation...")
                    panel_exists = await page.evaluate('''
                        () => {
                            const newPanel = document.querySelector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]');
                            const oldPanel = document.querySelector('.jobs-search__job-details');
                            return (newPanel !== null) || (oldPanel !== null);
                        }
                    ''')
                    if panel_exists:
                        details_panel = await page.query_selector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]') or await page.query_selector('.jobs-search__job-details')
                        if details_panel:
                            logger.info("Job details panel found (via evaluation)")
                            panel_found = True
                except Exception as e:
                    logger.debug(f"Browser evaluation check failed: {e}")
            
            # Strategy 3: Check all frames
            if not panel_found:
                try:
                    logger.debug("Checking all frames for details panel...")
                    frames = page.frames if hasattr(page, 'frames') else []
                    for i, frame in enumerate(frames):
                        try:
                            panel_exists = await frame.evaluate('''
                                () => {
                                    const newPanel = document.querySelector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]');
                                    const oldPanel = document.querySelector('.jobs-search__job-details');
                                    return (newPanel !== null) || (oldPanel !== null);
                                }
                            ''')
                            if panel_exists:
                                details_panel = await frame.query_selector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]') or await frame.query_selector('.jobs-search__job-details')
                                if details_panel:
                                    logger.info(f"Job details panel found in frame {i}")
                                    panel_found = True
                                    # Update page reference to the frame where panel was found
                                    page = frame
                                    break
                        except:
                            continue
                except Exception as e:
                    logger.debug(f"Frame check failed: {e}")
            
            # Strategy 4: Try visible state
            if not panel_found:
                try:
                    logger.debug("Trying to wait for panel to become visible...")
                    # Try new UI first
                    try:
                        await page.wait_for_selector(
                            'div[role="main"][data-sdui-screen*="SemanticJobDetails"]',
                            state='visible',
                            timeout=2000
                        )
                        details_panel = await page.query_selector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]')
                        if details_panel:
                            logger.info("Job details panel is visible (new UI)")
                            panel_found = True
                    except:
                        # Fallback to old UI
                        await page.wait_for_selector(
                            '.jobs-search__job-details',
                            state='visible',
                            timeout=1000
                        )
                        details_panel = await page.query_selector('.jobs-search__job-details')
                        if details_panel:
                            logger.info("Job details panel is visible (old UI)")
                            panel_found = True
                except Exception as e:
                    logger.debug(f"Panel not visible: {e}")
            
            if not panel_found:
                logger.warning("Could not find job details panel with standard detection - will try to extract anyway")
                # Continue anyway - maybe the selectors will still work
                # Give it a moment for the panel to fully render
                await asyncio.sleep(1)
            
            # Try selectors in priority order (updated for new UI)
            company_url_selectors = [
                # New UI: Company link in top section (has /company/ and /life/)
                ('a[href*="/company/"][href*="/life/"]', 'new UI (top section)'),
                # New UI: Company link in "About the company" section
                ('div[componentkey*="AboutTheCompany"] a[href*="/company/"][href*="/life/"]', 'new UI (about company)'),
                # Old UI: Company name link in top card
                ('.job-details-jobs-unified-top-card__company-name a', 'old UI (top card)'),
                # Old UI: Company name in "About the company" section
                ('.jobs-company .artdeco-entity-lockup__title a', 'old UI (about company)'),
                # Generic: Any company link in job details (old UI)
                ('.jobs-search__job-details a[href*="/company/"]', 'generic (old UI)'),
            ]
            
            for selector, description in company_url_selectors:
                try:
                    logger.debug(f"Trying selector '{selector}' ({description})...")
                    company_link = await page.query_selector(selector)
                    if company_link:
                        logger.info(f"Found company link element using selector: {description}")
                        href = await company_link.get_attribute('href')
                        logger.debug(f"Raw href attribute: {href}")
                        if href:
                            # Normalize URL
                            if href.startswith('/'):
                                # Relative URL - make it absolute
                                company_url = f"https://www.linkedin.com{href}"
                                logger.debug(f"Converted relative URL to absolute: {company_url}")
                            elif href.startswith('http'):
                                # Already absolute
                                company_url = href
                                logger.debug(f"URL is already absolute: {company_url}")
                            else:
                                # Invalid format
                                logger.warning(f"Invalid URL format: {href}")
                                continue
                            
                            # Remove query parameters and normalize
                            if '?' in company_url:
                                original_url = company_url
                                company_url = company_url.split('?')[0]
                                logger.debug(f"Removed query parameters: {original_url} -> {company_url}")
                            
                            # Ensure it ends with /life or just /company/...
                            # LinkedIn company URLs typically end with /life
                            if not company_url.endswith('/life') and '/company/' in company_url:
                                # Check if it already has a path after /company/
                                parts = company_url.split('/company/')
                                if len(parts) > 1:
                                    company_slug = parts[1].split('/')[0].split('?')[0]
                                    original_url = company_url
                                    company_url = f"https://www.linkedin.com/company/{company_slug}/life"
                                    logger.debug(f"Normalized company URL: {original_url} -> {company_url}")
                            
                            logger.info(f"✓ Successfully extracted company URL: {company_url}")
                            return company_url
                        else:
                            logger.debug(f"Found element but href attribute is empty or None")
                    else:
                        logger.debug(f"No element found for selector: {description}")
                except Exception as e:
                    logger.warning(f"Error trying selector '{selector}' ({description}): {e}", exc_info=True)
                    continue
            
            logger.warning("Could not extract company URL from details panel - all selectors failed")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting company URL: {e}", exc_info=True)
            return None
    
    async def _extract_job_data_from_panel(self, page, job_id: str) -> Optional[dict]:
        """Extract job data from the right-side details panel after clicking a card
        
        Args:
            page: Playwright page (main page, not iframe)
            job_id: Job ID extracted from URL
            
        Returns:
            Dictionary with job data or None if extraction fails
        """
        try:
            logger.info(f"Extracting job data from panel for job ID: {job_id}")
            
            # Wait for panel to be ready
            await asyncio.sleep(1)
            
            # Find the panel
            panel = None
            try:
                # Try new UI first
                panel = await page.query_selector('div[role="main"][data-sdui-screen*="SemanticJobDetails"]')
                if not panel:
                    # Fallback to old UI
                    panel = await page.query_selector('.jobs-search__job-details')
            except:
                pass
            
            if not panel:
                logger.warning("Could not find details panel")
                return None
            
            # Extract title
            title = None
            title_selectors = [
                'a[href*="/jobs/view/"]',  # New UI: title is in a link
                'h1',  # Usually the job title is in h1
                'h2.jobs-details-top-card__job-title',
                '.job-details-jobs-unified-top-card__job-title',
                '[data-testid="job-title"]',
            ]
            for selector in title_selectors:
                try:
                    title_elem = await panel.query_selector(selector)
                    if title_elem:
                        title = await title_elem.inner_text()
                        if title:
                            title = title.strip()
                            break
                except:
                    continue
            
            # Extract company name
            company = None
            company_selectors = [
                'a[href*="/company/"][href*="/life/"]',  # Company link in new UI
                '.job-details-jobs-unified-top-card__company-name',
                '.jobs-company__box a',
            ]
            for selector in company_selectors:
                try:
                    company_elem = await panel.query_selector(selector)
                    if company_elem:
                        company = await company_elem.inner_text()
                        if company:
                            company = company.strip()
                            break
                except:
                    continue
            
            # Extract location
            location = None
            location_selectors = [
                '.job-details-jobs-unified-top-card__primary-description-without-tagline',
                '.jobs-details-top-card__primary-description',
                '[data-testid="job-location"]',
            ]
            for selector in location_selectors:
                try:
                    loc_elem = await panel.query_selector(selector)
                    if loc_elem:
                        location_text = await loc_elem.inner_text()
                        if location_text:
                            # Extract location part (before "·" or " - ")
                            location = location_text.split('·')[0].split(' - ')[0].strip()
                            if location:
                                break
                except:
                    continue
            
            # Construct job URL
            job_url = f"https://www.linkedin.com/jobs/view/{job_id}/"
            
            # Extract posted date (if available)
            posted_date = None
            date_selectors = [
                'time[datetime]',
                '.jobs-details-top-card__posted-date',
            ]
            for selector in date_selectors:
                try:
                    date_elem = await panel.query_selector(selector)
                    if date_elem:
                        datetime_attr = await date_elem.get_attribute('datetime')
                        if datetime_attr:
                            posted_date = datetime_attr.strip()
                            break
                        date_text = await date_elem.inner_text()
                        if date_text:
                            posted_date = date_text.strip()
                            break
                except:
                    continue
            
            if not title:
                logger.warning("Could not extract title from panel")
                # Use fallback title
                title = f"Job {job_id}"
            
            logger.info(f"Extracted from panel: title={title}, company={company}, location={location}")
            
            return {
                'title': title,
                'company': company,
                'location': location,
                'posted_date': posted_date,
                'url': job_url,
                'job_id': job_id
            }
            
        except Exception as e:
            logger.error(f"Error extracting job data from panel: {e}", exc_info=True)
            return None
    
    async def scrape_jobs(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience_level: Optional[str] = None,
        job_type: Optional[str] = None,
        max_results: int = 10
    ) -> List[JobListing]:
        """
        Scrape LinkedIn jobs
        
        Args:
            keywords: Job search keywords
            location: Location filter (optional)
            experience_level: Experience level filter (optional)
            job_type: Job type filter (optional)
            max_results: Maximum number of jobs to scrape
        
        Returns:
            List of JobListing objects
        """
        logger.info(f"Starting job scrape: keywords='{keywords}', location='{location}', max_results={max_results}")
        
        try:
            # Get Playwright page
            logger.info("Getting Playwright page...")
            page = await self._get_page()  # Uses self.headless
            logger.info(f"Got page, current URL: {page.url}")
            
            # Navigate to LinkedIn Jobs (assumes already logged in via cookies)
            logger.info("Navigating to LinkedIn Jobs page...")
            await self._navigate_to_jobs_page(page)
            
            # Perform search with separate title and location fields
            # This method now handles waiting for results to load
            await self._search_jobs(page, keywords=keywords, location=location)
            
            # Brief verification that we're on results page (already checked in _search_jobs)
            logger.debug(f"Current page URL: {page.url}")
            
            # Apply date filter (Past 24 hours) before scrolling
            await self._apply_date_filter(page)
            
            # Apply filters if provided
            if experience_level or job_type:
                await self._apply_filters(page, experience_level, job_type)
            
            # Scroll to load more jobs
            await self._scroll_job_list(page, max_results)
            
            # Extract job data
            logger.info("Extracting job data from cards...")
            list_items = []  # Initialize list_items
            
            # Find the frame that contains job cards (iframes are common)
            target_frame = await self._find_target_frame(page)
            extraction_page = target_frame if target_frame else page
            if target_frame:
                logger.debug("Using iframe for job extraction")
            
            # Try using browser context evaluation (more reliable for dynamic content)
            # Check for both new UI and old UI structures
            try:
                # Check for new UI first
                new_ui_count = await extraction_page.evaluate('document.querySelectorAll("[data-view-name=\\"job-search-job-card\\"]").length')
                old_ui_count = await extraction_page.evaluate('document.querySelectorAll("[data-job-id]").length')
                
                logger.info(f"Browser context check: Found {new_ui_count} NEW UI cards, {old_ui_count} OLD UI cards")
                
                if new_ui_count > 0:
                    # New UI: Get all div[data-view-name="job-search-job-card"] elements
                    logger.debug("Using NEW UI structure (div-based)")
                    new_ui_cards = await extraction_page.query_selector_all('div[data-view-name="job-search-job-card"]')
                    logger.info(f"Found {len(new_ui_cards)} job cards using NEW UI structure")
                    list_items = new_ui_cards
                elif old_ui_count > 0:
                    # Old UI: Get all li elements and check which ones contain job cards
                    logger.debug("Using OLD UI structure (li-based)")
                    all_lis = await extraction_page.query_selector_all('li')
                    logger.debug(f"Checking {len(all_lis)} li elements for job cards...")
                    
                    # Use browser evaluation to check which li elements contain job cards
                    valid_li_indices = await extraction_page.evaluate('''
                        () => {
                            const cards = document.querySelectorAll('[data-job-id]');
                            const allLis = document.querySelectorAll('li');
                            const validIndices = new Set();
                            
                            cards.forEach(card => {
                                let parent = card.parentElement;
                                while (parent) {
                                    if (parent.tagName === 'LI') {
                                        const index = Array.from(allLis).indexOf(parent);
                                        if (index >= 0) {
                                            validIndices.add(index);
                                        }
                                        break;
                                    }
                                    parent = parent.parentElement;
                                }
                            });
                            
                            return Array.from(validIndices);
                        }
                    ''')
                    
                    logger.debug(f"Found {len(valid_li_indices)} li elements containing job cards")
                    for idx in valid_li_indices:
                        if idx < len(all_lis):
                            list_items.append(all_lis[idx])
                    
                    if list_items:
                        logger.debug(f"Successfully found {len(list_items)} list items via browser context evaluation")
            except Exception as e:
                logger.warning(f"Browser context evaluation failed: {e}", exc_info=True)
            
            # Fallback to standard selectors if browser context didn't work
            if not list_items:
                # Try new UI selectors first
                try:
                    new_ui_cards = await extraction_page.query_selector_all('div[data-view-name="job-search-job-card"]')
                    if new_ui_cards:
                        logger.info(f"Found {len(new_ui_cards)} job cards using NEW UI fallback selector")
                        list_items = new_ui_cards
                except:
                    pass
                
                # Then try old UI selectors
                if not list_items:
                    list_item_selectors = [
                        'li.scaffold-layout__list-item',  # Double underscore
                        'li.scaffold-layout_list-item',  # Single underscore variant
                        'li[data-occludable-job-id]',  # By data attribute
                        'li[class*="scaffold-layout__list-item"]',  # Double underscore partial match
                        'li[class*="scaffold-layout_list-item"]',  # Single underscore partial match
                    ]
                    
                    for selector in list_item_selectors:
                        try:
                            items = await extraction_page.query_selector_all(selector)
                            if items:
                                logger.info(f"Found {len(items)} list items using OLD UI selector: {selector}")
                                list_items = items
                                break
                        except Exception as e:
                            logger.debug(f"Selector '{selector}' failed: {e}")
                            continue
            
            if not list_items:
                logger.debug("No list items found with standard selectors. Trying fallback...")
                # Fallback: try to find new UI cards first, then old UI
                try:
                    # Try new UI
                    new_ui_cards = await extraction_page.query_selector_all('div[data-view-name="job-search-job-card"]')
                    if new_ui_cards:
                        logger.debug(f"Found {len(new_ui_cards)} NEW UI cards in fallback")
                        list_items = new_ui_cards
                    else:
                        # Try old UI
                        all_lis = await extraction_page.query_selector_all('li')
                        logger.debug(f"Found {len(all_lis)} total <li> elements, checking for job cards...")
                        for li in all_lis:
                            try:
                                has_job_id = await li.query_selector('[data-job-id]')
                                has_occludable = await li.get_attribute('data-occludable-job-id')
                                
                                if has_job_id or has_occludable:
                                    # Verify it's a real job card by checking for title link
                                    title_link = await li.query_selector('a.job-card-container__link, a[href*="/jobs/view/"]')
                                    if title_link:
                                        list_items.append(li)
                            except:
                                pass
                        logger.debug(f"Found {len(list_items)} list items with job data after fallback")
                except Exception as e:
                    logger.debug(f"Fallback failed: {e}")
            
            logger.info(f"Found {len(list_items)} job cards to extract")
            
            job_listings = []
            extracted_job_ids = set()  # Track extracted job IDs to avoid duplicates
            
            for i, list_item in enumerate(list_items):
                if len(job_listings) >= max_results:
                    break
                
                # Skip placeholder items
                # Debug: Check what's in the card
                try:
                    view_name = await list_item.get_attribute('data-view-name')
                    has_button = await list_item.query_selector('div[role="button"]')
                    link_count = len(await list_item.query_selector_all('a'))
                    logger.debug(f"Card {i+1} check: view_name={view_name}, has_button={has_button is not None}, link_count={link_count}")
                except:
                    pass
                
                is_valid = await self._is_valid_job_card(list_item)
                if not is_valid:
                    logger.warning(f"Skipping card {i+1}/{len(list_items)}: not a valid job card (view_name={view_name if 'view_name' in locals() else 'unknown'})")
                    continue
                
                logger.info(f"Processing card {i+1}/{len(list_items)}...")
                
                # Debug: Check what's actually in the card using browser evaluation
                try:
                    card_info = await extraction_page.evaluate('''(element) => {
                        const viewName = element.getAttribute('data-view-name');
                        const links = element.querySelectorAll('a');
                        const linkHrefs = Array.from(links).map(a => a.getAttribute('href')).filter(Boolean);
                        const jobLinks = linkHrefs.filter(href => href.includes('/jobs/view/'));
                        return {
                            viewName: viewName,
                            totalLinks: links.length,
                            jobLinks: jobLinks.length,
                            firstJobLink: jobLinks[0] || null
                        };
                    }''', list_item)
                    logger.info(f"Card {i+1} debug info: {card_info}")
                except Exception as e:
                    logger.debug(f"Could not evaluate card {i+1}: {e}")
                
                # NEW APPROACH: Click first, then extract from right panel
                # Since links aren't accessible in card elements, we click to open the panel
                # and extract everything from there
                click_context = extraction_page if target_frame else page
                logger.info(f"Clicking card {i+1} to open details panel...")
                
                # Store current URL to detect changes
                current_url_before = page.url
                
                try:
                    # Click the card to open the right panel
                    click_success = await self._click_job_card(click_context, list_item, main_page=page)
                    if not click_success:
                        logger.warning(f"Failed to click card {i+1}, skipping...")
                        continue
                    
                    # Wait a moment for the click to register and panel to start loading
                    await asyncio.sleep(2)  # Give panel time to start loading after click
                    
                    # Wait for URL to update with currentJobId (indicates panel loaded)
                    logger.debug("Waiting for URL to update with job ID...")
                    try:
                        await page.wait_for_function(
                            '() => window.location.href.includes("currentJobId")',
                            timeout=5000
                        )
                        await asyncio.sleep(2)  # Give panel additional time to fully load
                    except:
                        logger.debug("URL didn't update with currentJobId, but continuing...")
                    
                    # Extract job ID from URL
                    current_url_after = page.url
                    job_id = self._extract_job_id(current_url_after)
                    
                    if not job_id:
                        logger.warning(f"Could not extract job ID from URL after clicking card {i+1}: {current_url_after}")
                        # Try to extract from URL params
                        if 'currentJobId' in current_url_after:
                            import urllib.parse
                            parsed = urllib.parse.urlparse(current_url_after)
                            params = urllib.parse.parse_qs(parsed.query)
                            if 'currentJobId' in params:
                                job_id = params['currentJobId'][0]
                    
                    if not job_id:
                        logger.warning(f"Skipping card {i+1}: could not extract job ID")
                        continue
                    
                    # Skip if we've already extracted this job ID
                    if job_id in extracted_job_ids:
                        logger.debug(f"Skipping duplicate job ID: {job_id}")
                        continue
                    extracted_job_ids.add(job_id)
                    
                    logger.info(f"✓ Extracted job ID {job_id} from URL after clicking card {i+1}")
                    
                    # Now extract all data from the right panel
                    job_data = await self._extract_job_data_from_panel(page, job_id)
                    
                    if not job_data:
                        logger.warning(f"Could not extract job data from panel for job {job_id}")
                        continue
                    
                    logger.info(f"✓ Successfully extracted job {i+1}: {job_data.get('title', 'Unknown')} (ID: {job_id})")
                    
                    # Extract company URL from the panel
                    company_url = await self._extract_company_url_from_details_panel(page)
                    if company_url:
                        logger.info(f"✓ Successfully extracted company URL: {company_url}")
                    else:
                        logger.warning(f"✗ Could not extract company URL from details panel")
                    
                    # Initialize posted_date before conditional assignment
                    posted_date = None
                    if job_data.get('posted_date'):
                        try:
                            # Try to parse relative dates like "2 days ago"
                            date_str = job_data['posted_date'].lower()
                            if 'ago' in date_str or 'day' in date_str:
                                # For now, just store as string
                                # Could implement proper parsing later
                                posted_date = None
                            else:
                                # Try ISO format or other formats
                                posted_date = datetime.fromisoformat(job_data['posted_date'])
                        except:
                            posted_date = None
                    
                    # Set defaults for missing fields
                    experience_level_val = None  # Could extract from panel if needed
                    job_type_val = None  # Could extract from panel if needed
                    
                    try:
                        logger.debug(f"Creating JobListing for job {job_id} with company_url: {company_url}")
                        job_listing = JobListing(
                            job_id=job_id,
                            title=job_data.get('title', ''),
                            company=job_data.get('company', ''),
                            url=job_data.get('url', 'https://www.linkedin.com/jobs'),
                            company_url=company_url,
                            location=job_data.get('location'),
                            description=None,  # Could be extracted by clicking into job details
                            posted_date=posted_date,
                            skills=[],
                            experience_level=experience_level_val,
                            job_type=job_type_val,
                            status='pending'
                        )
                        logger.info(f"Created JobListing for '{job_listing.title}' at '{job_listing.company}' - company_url: {job_listing.company_url}")
                        job_listings.append(job_listing)
                    except Exception as e:
                        logger.error(f"Error creating JobListing from data: {e}", exc_info=True)
                        continue
                    
                except Exception as e:
                    logger.error(f"Error processing card {i+1}: {e}", exc_info=True)
                    continue
            
            logger.info(f"Successfully scraped {len(job_listings)} jobs")
            return job_listings
            
        except Exception as e:
            logger.error(f"Error scraping jobs: {e}", exc_info=True)
            raise
    
    async def scrape_jobs_simple(self, keywords: str, location: Optional[str] = None) -> List[JobListing]:
        """Simplified scraping method"""
        return await self.scrape_jobs(keywords=keywords, location=location)
    
    async def close(self):
        """Close browser page if open"""
        if self.page and not self.page.is_closed():
            await self.page.close()
            self.page = None
