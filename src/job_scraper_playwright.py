"""LinkedIn job scraper using Playwright"""

import os
import re
import asyncio
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
        
        await asyncio.sleep(3)  # Wait for results to load
        logger.info("Search submitted, waiting for results...")
    
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
    
    async def _scroll_job_list(self, page, max_results: int):
        """Scroll through job list to load more jobs"""
        logger.info(f"Scrolling job list to load at least {max_results} jobs...")
        
        # Find the job list container (left sidebar)
        job_list_selectors = [
            '.jobs-search-results__list',
            '.scaffold-layout__list-container',
            'ul.scaffold-layout__list-container',
            '[data-test-id="job-list"]',
        ]
        
        job_list_container = None
        for selector in job_list_selectors:
            try:
                job_list_container = await page.wait_for_selector(selector, timeout=5000)
                if job_list_container:
                    logger.debug(f"Found job list container using selector: {selector}")
                    break
            except:
                continue
        
        if not job_list_container:
            logger.warning("Could not find job list container, trying to scroll page")
            job_list_container = page
        
        # Track visible jobs to detect when new ones load
        previous_count = 0
        scroll_attempts = 0
        max_scroll_attempts = 50
        
        while scroll_attempts < max_scroll_attempts:
            # Count current visible job cards
            job_cards = await page.query_selector_all('.job-card-container, .jobs-search-results__list-item, [data-test-id="job-card"]')
            current_count = len(job_cards)
            
            logger.debug(f"Found {current_count} job cards (target: {max_results})")
            
            if current_count >= max_results:
                logger.info(f"Found {current_count} jobs, target reached")
                break
            
            # Scroll within the job list container
            try:
                await job_list_container.evaluate('''
                    element => {
                        element.scrollTop += 500;
                    }
                ''')
            except:
                # Fallback to page scroll
                await page.evaluate('window.scrollBy(0, 500)')
            
            await asyncio.sleep(1)  # Wait for lazy loading
            
            # Check if new jobs loaded
            new_job_cards = await page.query_selector_all('.job-card-container, .jobs-search-results__list-item, [data-test-id="job-card"]')
            new_count = len(new_job_cards)
            
            if new_count == previous_count:
                scroll_attempts += 1
                # Try clicking "Show more" button if it exists
                try:
                    show_more_button = await page.query_selector('button:has-text("Show more"), button[aria-label*="Show more"]')
                    if show_more_button:
                        await show_more_button.click()
                        await asyncio.sleep(2)
                        scroll_attempts = 0  # Reset counter
                except:
                    pass
            else:
                scroll_attempts = 0  # Reset counter when new jobs load
            
            previous_count = new_count
            
            # Small random delay to mimic human behavior
            await asyncio.sleep(0.5)
        
        job_card_selector = '.job-card-container, .jobs-search-results__list-item, [data-test-id="job-card"]'
        job_cards = await page.query_selector_all(job_card_selector)
        logger.info(f"Finished scrolling. Found {len(job_cards)} job cards")
    
    async def _extract_job_card(self, card_element) -> Optional[dict]:
        """Extract job data from a single job card element"""
        try:
            # Extract job title
            title_selectors = [
                '.job-card-list__title',
                'a[data-control-name="job_card_title"]',
                '.job-card-container__link',
                'h3 a',
                '.job-title',
            ]
            title = None
            job_url = None
            
            for selector in title_selectors:
                try:
                    title_elem = await card_element.query_selector(selector)
                    if title_elem:
                        title = await title_elem.inner_text()
                        # Try to get URL from title link
                        href = await title_elem.get_attribute('href')
                        if href:
                            if href.startswith('/'):
                                job_url = f"https://www.linkedin.com{href}"
                            else:
                                job_url = href
                        break
                except:
                    continue
            
            if not title:
                return None
            
            # Extract company name
            company_selectors = [
                '.job-card-container__company-name',
                '.job-card-container__primary-description',
                '[data-test-id="job-card-company-name"]',
                '.job-card-company-name',
            ]
            company = None
            
            for selector in company_selectors:
                try:
                    company_elem = await card_element.query_selector(selector)
                    if company_elem:
                        company = await company_elem.inner_text()
                        if company:
                            break
                except:
                    continue
            
            if not company:
                return None
            
            # Extract location
            location_selectors = [
                '.job-card-container__metadata-item',
                '.job-card-container__metadata-wrapper li',
                '[data-test-id="job-card-location"]',
                '.job-card-location',
            ]
            location = None
            
            for selector in location_selectors:
                try:
                    location_elem = await card_element.query_selector(selector)
                    if location_elem:
                        location_text = await location_elem.inner_text()
                        # Filter out "Posted" or date-like text
                        if location_text and 'ago' not in location_text.lower() and 'day' not in location_text.lower():
                            location = location_text.strip()
                            break
                except:
                    continue
            
            # Extract posted date
            date_selectors = [
                '.job-card-container__listed-time',
                'time',
                '[data-test-id="job-card-posted-date"]',
            ]
            posted_date = None
            
            for selector in date_selectors:
                try:
                    date_elem = await card_element.query_selector(selector)
                    if date_elem:
                        date_text = await date_elem.inner_text() or await date_elem.get_attribute('datetime')
                        if date_text:
                            # Parse relative dates like "2 days ago" or absolute dates
                            posted_date = date_text.strip()
                            break
                except:
                    continue
            
            # If no URL found, try to get it from card's clickable area
            if not job_url:
                try:
                    link = await card_element.query_selector('a')
                    if link:
                        href = await link.get_attribute('href')
                        if href:
                            if href.startswith('/'):
                                job_url = f"https://www.linkedin.com{href}"
                            else:
                                job_url = href
                except:
                    pass
            
            return {
                'title': title.strip(),
                'company': company.strip(),
                'location': location.strip() if location else None,
                'posted_date': posted_date.strip() if posted_date else None,
                'url': job_url or "https://www.linkedin.com/jobs"
            }
        except Exception as e:
            logger.debug(f"Error extracting job card data: {e}")
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
            await self._search_jobs(page, keywords=keywords, location=location)
            
            # Apply filters if provided
            if experience_level or job_type:
                await self._apply_filters(page, experience_level, job_type)
            
            # Scroll to load more jobs
            await self._scroll_job_list(page, max_results)
            
            # Extract job data
            logger.info("Extracting job data from cards...")
            job_cards = await page.query_selector_all(
                '.job-card-container, .jobs-search-results__list-item, [data-test-id="job-card"]'
            )
            
            logger.info(f"Found {len(job_cards)} job cards to extract")
            
            job_listings = []
            for i, card in enumerate(job_cards[:max_results * 2]):  # Get extra in case some fail
                if len(job_listings) >= max_results:
                    break
                
                job_data = await self._extract_job_card(card)
                if not job_data:
                    continue
                
                # Extract job ID from URL
                job_id = self._extract_job_id(job_data.get('url', ''))
                
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
