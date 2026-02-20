"""LinkedIn job scraper using Playwright"""

import os
import re
import asyncio
import time
from typing import List, Optional
from urllib.parse import urlparse, parse_qs
from datetime import datetime
from dotenv import load_dotenv

from src.models import JobListing
from src.session_manager import SessionManager
from src.utils.logger import logger

load_dotenv()


class JobScraperPlaywright:
    """Scrape LinkedIn jobs using Playwright"""
    
    def __init__(self, model: Optional[str] = None, browser=None, playwright_browser=None):
        """Initialize job scraper
        
        Args:
            model: Optional model name override (kept for backward compatibility)
            browser: Optional browser-use Browser instance (backward compatibility)
            playwright_browser: Optional Playwright Browser instance
        """
        self.model = model  # Kept for backward compatibility but not used
        self.browser = browser  # Kept for backward compatibility
        self.playwright_browser = playwright_browser
        self.session_manager = SessionManager()
        self.page = None
    
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
    
    async def _get_page(self, headless: bool = False):
        """Get or create a Playwright page"""
        if self.page and not self.page.is_closed():
            return self.page
        
        # Get browser context
        if not self.playwright_browser:
            self.playwright_browser = await self.session_manager.get_playwright_browser(headless=headless)
        
        # Get pages from browser (persistent context returns pages directly)
        pages = self.playwright_browser.pages
        if pages:
            self.page = pages[0]
        else:
            self.page = await self.playwright_browser.new_page()
        
        return self.page
    
    async def _navigate_to_jobs_page(self, page):
        """Navigate to LinkedIn Jobs page"""
        logger.info("Navigating to LinkedIn Jobs page...")
        await page.goto("https://www.linkedin.com/jobs", wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)  # Wait for page to fully load
        logger.info("Successfully navigated to LinkedIn Jobs page")
    
    async def _find_title_input(self, page):
        """Find the title/keywords search input field"""
        # Priority order: most specific to least specific
        title_selectors = [
            'input[componentkey="jobSearchBox"]',
            'input[placeholder*="Title, skill or Company"]',
            'input[placeholder*="Title"]',
            'input[data-testid="typeahead-input"][placeholder*="Title"]',
        ]
        
        for selector in title_selectors:
            try:
                title_input = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if title_input:
                    # Verify it's the title field by checking placeholder
                    placeholder = await title_input.get_attribute('placeholder') or ''
                    if 'Title' in placeholder or 'skill' in placeholder.lower() or 'Company' in placeholder:
                        logger.debug(f"Found title input using selector: {selector}")
                        return title_input
            except:
                continue
        
        # Fallback: find all typeahead inputs and identify by placeholder
        try:
            all_inputs = await page.query_selector_all('input[data-testid="typeahead-input"]')
            for input_elem in all_inputs:
                placeholder = await input_elem.get_attribute('placeholder') or ''
                if 'Title' in placeholder or 'skill' in placeholder.lower() or 'Company' in placeholder:
                    logger.debug("Found title input using fallback method")
                    return input_elem
        except:
            pass
        
        return None
    
    async def _find_location_input(self, page):
        """Find the location search input field"""
        # Priority order: most specific to least specific
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
                        logger.debug(f"Found location input using selector: {selector}")
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
        
        return None
    
    async def _search_jobs(self, page, keywords: str, location: Optional[str] = None):
        """Enter search query in LinkedIn Jobs search using separate title and location fields"""
        logger.info(f"Searching for jobs: keywords='{keywords}', location='{location}'")
        
        # Find and fill title/keywords field
        title_input = await self._find_title_input(page)
        if not title_input:
            # Log available inputs for debugging
            try:
                all_inputs = await page.query_selector_all('input[data-testid="typeahead-input"]')
                logger.error(f"Could not find title input. Found {len(all_inputs)} typeahead inputs:")
                for i, inp in enumerate(all_inputs):
                    placeholder = await inp.get_attribute('placeholder') or 'N/A'
                    logger.error(f"  Input {i+1}: placeholder='{placeholder}'")
            except:
                pass
            raise Exception("Could not find LinkedIn job title/keywords search input field")
        
        # Enter keywords in title field
        await title_input.click()
        await asyncio.sleep(0.3)  # Small delay for focus
        await title_input.fill("")  # Clear any existing text
        await title_input.type(keywords, delay=50)  # Type with delay to mimic human behavior
        await asyncio.sleep(0.5)  # Wait for any autocomplete to appear
        
        # If location is provided, find and fill location field
        if location:
            location_input = await self._find_location_input(page)
            if not location_input:
                logger.warning(f"Could not find location input field. Continuing search without location filter.")
            else:
                # Enter location in location field
                await location_input.click()
                await asyncio.sleep(0.3)  # Small delay for focus
                await location_input.fill("")  # Clear any existing text
                await location_input.type(location, delay=50)
                await asyncio.sleep(0.5)  # Wait for any autocomplete to appear
                
                # Submit search by pressing Enter on location field
                await location_input.press("Enter")
        else:
            # Submit search by pressing Enter on title field
            await title_input.press("Enter")
        
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
                job_count = await page.evaluate('''
                    () => {
                        return document.querySelectorAll('[data-job-id]').length;
                    }
                ''')
                
                if job_count > 0:
                    logger.info(f"Found {job_count} job cards using browser context evaluation!")
                    job_results_found = True
                    break
                
                # Also check using Playwright selectors
                job_indicators = [
                    '[data-job-id]',
                    '.job-card-container',
                    'li[data-occludable-job-id]',
                    '[class*="job-card"]',
                    '[class*="jobs-search-results"]',
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
                            iframe_job_count = await frame.evaluate('document.querySelectorAll("[data-job-id]").length')
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
        """Find the job list container (ul element) using stable semantic selectors"""
        # Priority selectors using stable class names (no random strings)
        # Note: LinkedIn may use single or double underscores in class names
        list_selectors = [
            '.scaffold-layout__list > ul',  # Direct child ul of scaffold-layout__list (double underscore)
            '.scaffold-layout__list ul',  # Descendant ul (more flexible)
            '.scaffold-layout_list > ul',  # Single underscore variant
            '.scaffold-layout_list ul',  # Single underscore variant descendant
            'ul[class*="scaffold-layout"]',  # Fallback: any ul with scaffold-layout in class
            'ul.scaffold-layout__list-container',  # Alternative stable class
            '.scaffold-layout__list',  # Try the parent div itself (double underscore)
            '.scaffold-layout_list',  # Try the parent div itself (single underscore)
        ]
        
        logger.info("Attempting to find job list container...")
        for selector in list_selectors:
            try:
                logger.debug(f"Trying selector: {selector}")
                list_container = await page.wait_for_selector(selector, timeout=3000, state="visible")
                if list_container:
                    logger.info(f"Found job list container using selector: {selector}")
                    return list_container
            except Exception as e:
                logger.debug(f"Selector '{selector}' failed: {e}")
                continue
        
        # Debug: Log what's actually on the page (only if selector fails)
        logger.warning("Could not find job list container with specific selectors.")
        try:
            # Quick check for job cards using browser context
            job_count_browser = await page.evaluate('document.querySelectorAll("[data-job-id]").length')
            logger.debug(f"Browser context check: Found {job_count_browser} elements with [data-job-id]")
            
            # Check for ul elements
            all_uls = await page.query_selector_all('ul')
            logger.debug(f"Found {len(all_uls)} <ul> elements on the page")
            
        except Exception as e:
            logger.debug(f"Error during debugging: {e}")
        
        return None
    
    async def _find_target_frame(self, page):
        """Find the frame that contains job cards"""
        frames = page.frames
        for i, frame in enumerate(frames):
            try:
                job_count = await frame.evaluate('document.querySelectorAll("[data-job-id]").length')
                if job_count > 0:
                    logger.debug(f"Found {job_count} job cards in frame {i}")
                    return frame
            except:
                continue
        return None
    
    async def _get_job_ids(self, page):
        """Extract unique job IDs from visible job cards"""
        job_ids = set()
        
        # First, try to find the frame with job cards
        target_frame = await self._find_target_frame(page)
        extraction_page = target_frame if target_frame else page
        
        # Find all li elements with job IDs (both data-job-id and data-occludable-job-id)
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
                        logger.debug(f"Found {len(items)} list items using selector: {selector}")
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
            
            logger.debug(f"Processing {len(list_items)} list items for job IDs")
            
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
    
    async def _is_valid_job_card(self, list_item):
        """Check if a list item contains a valid job card (not a placeholder)"""
        try:
            # Check if it has a job-card-container with data-job-id
            card = await list_item.query_selector('[data-job-id]')
            if card:
                # Check if it has actual content (title link)
                title_link = await card.query_selector('a.job-card-container__link')
                return title_link is not None
            return False
        except:
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
                # Try multiple selectors for list items
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
        """Extract job data from a single job card element (li.scaffold-layout__list-item)"""
        try:
            # First, try to get the job card container with data-job-id
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
            
            # Extract company name
            company_selectors = [
                '.artdeco-entity-lockup__subtitle span',  # Actual structure
                '.artdeco-entity-lockup__subtitle',  # Fallback
            ]
            company = None
            
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
            
            if not company:
                logger.debug(f"Could not extract company name for job: {title}")
                # Don't return None - company might be optional in some cases
            
            # Extract location
            location_selectors = [
                '.job-card-container__metadata-wrapper li span',  # Actual structure
                '.job-card-container__metadata-wrapper span',  # Fallback
                '.job-card-container__metadata-wrapper li',  # Another fallback
            ]
            location = None
            
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
            
            # Extract posted date
            date_selectors = [
                '.job-card-container__footer-item time',  # Has datetime attribute
                'time[datetime]',  # Fallback
                '.job-card-container__footer-item',  # Another fallback
            ]
            posted_date = None
            
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
            page = await self._get_page(headless=False)
            
            # Navigate to LinkedIn Jobs (assumes already logged in via cookies)
            await self._navigate_to_jobs_page(page)
            
            # Perform search with separate title and location fields
            # This method now handles waiting for results to load
            await self._search_jobs(page, keywords=keywords, location=location)
            
            # Brief verification that we're on results page (already checked in _search_jobs)
            logger.debug(f"Current page URL: {page.url}")
            
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
            try:
                job_cards_count = await extraction_page.evaluate('document.querySelectorAll("[data-job-id]").length')
                logger.info(f"Browser context check: Found {job_cards_count} elements with [data-job-id]")
                
                if job_cards_count > 0:
                    # Get all li elements and check which ones contain job cards using browser evaluation
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
                # Query for list items (li elements) which contain the job cards
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
                            logger.info(f"Found {len(items)} list items using selector: {selector}")
                            list_items = items
                            break
                    except Exception as e:
                        logger.debug(f"Selector '{selector}' failed: {e}")
                        continue
            
            if not list_items:
                logger.debug("No list items found with standard selectors. Trying fallback...")
                # Fallback: try to find any li with data-occludable-job-id or data-job-id
                try:
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
            
            logger.info(f"Found {len(list_items)} list items to extract")
            
            job_listings = []
            extracted_job_ids = set()  # Track extracted job IDs to avoid duplicates
            
            for i, list_item in enumerate(list_items):
                if len(job_listings) >= max_results:
                    break
                
                # Skip placeholder items
                if not await self._is_valid_job_card(list_item):
                    continue
                
                job_data = await self._extract_job_card(list_item)
                if not job_data:
                    continue
                
                # Use job_id from extracted data if available, otherwise extract from URL
                job_id = job_data.get('job_id')
                if not job_id:
                    job_id = self._extract_job_id(job_data.get('url', ''))
                
                # Skip if we've already extracted this job ID
                if job_id:
                    if job_id in extracted_job_ids:
                        logger.debug(f"Skipping duplicate job ID: {job_id}")
                        continue
                    extracted_job_ids.add(job_id)
                else:
                    # If we can't get job_id, log warning but continue
                    logger.warning(f"Could not extract job_id for job: {job_data.get('title', 'Unknown')}")
                
                # Parse posted_date if it's a string
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
                
                try:
                    job_listing = JobListing(
                        job_id=job_id,
                        title=job_data.get('title', ''),
                        company=job_data.get('company', ''),
                        url=job_data.get('url', 'https://www.linkedin.com/jobs'),
                        location=job_data.get('location'),
                        description=None,  # Could be extracted by clicking into job details
                        posted_date=posted_date,
                        skills=[],
                        experience_level=experience_level,
                        job_type=job_type,
                        status='pending'
                    )
                    job_listings.append(job_listing)
                except Exception as e:
                    logger.error(f"Error creating JobListing from data: {e}")
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
