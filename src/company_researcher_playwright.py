"""Company research module using Playwright (no browser-use)"""

import asyncio
import re
from typing import Optional, Dict, Any, List

from src.models import CompanyResearch, JobListing
from src.database import Database
from src.session_manager import SessionManager
from src.utils.logger import logger


class CompanyResearcherPlaywright:
    """Research companies using Playwright - scrapes LinkedIn About page directly"""

    def __init__(
        self,
        db: Optional[Database] = None,
        playwright_browser=None,
        headless: bool = False,
    ):
        """Initialize company researcher with Playwright

        Args:
            db: Optional Database instance for saving research
            playwright_browser: Optional Playwright Browser instance (reused if provided)
            headless: Whether to run browser in headless mode (default: False)
        """
        self.db = db
        self.playwright_browser = playwright_browser
        self.session_manager = SessionManager()
        self.page = None
        self.headless = headless

    def _get_linkedin_about_url(self, company_url: str) -> str:
        """
        Construct LinkedIn about page URL from company URL

        Args:
            company_url: LinkedIn company page URL (e.g., https://www.linkedin.com/company/example/life)

        Returns:
            LinkedIn about page URL (e.g., https://www.linkedin.com/company/example/about)
        """
        url = company_url.rstrip("/")

        if "/company/" in url:
            parts = url.split("/company/")
            if len(parts) > 1:
                company_slug = parts[1].split("/")[0]
                return f"https://www.linkedin.com/company/{company_slug}/about"

        if url.endswith("/life"):
            return url.replace("/life", "/about")

        return f"{url}/about"

    def _get_linkedin_people_url(self, company_url: str) -> str:
        """
        Construct LinkedIn People page URL from company URL.

        Args:
            company_url: LinkedIn company page URL (e.g., https://www.linkedin.com/company/example)

        Returns:
            LinkedIn People page URL (e.g., https://www.linkedin.com/company/example/people)
        """
        url = company_url.rstrip("/")
        if "/company/" in url:
            parts = url.split("/company/")
            if len(parts) > 1:
                company_slug = parts[1].split("/")[0]
                return f"https://www.linkedin.com/company/{company_slug}/people"
        return f"{url}/people"

    def _filter_key_contacts(
        self,
        people_list: List[Dict[str, Optional[str]]],
        keywords: Optional[List[str]] = None,
        max_results: int = 2,
    ) -> List[Dict[str, Optional[str]]]:
        """
        Filter people by keywords in name or job_title, return up to max_results.

        Args:
            people_list: Full list of people from People you may know
            keywords: Keywords to match (case-insensitive). Default: engineer, hr, hiring
            max_results: Maximum number of contacts to return (default 2)

        Returns:
            List of matching people, max max_results items
        """
        if keywords is None:
            keywords = ["engineer", "hr", "hiring"]
        keywords_lower = [kw.lower() for kw in keywords]
        matches: List[Dict[str, Optional[str]]] = []
        for person in people_list:
            if len(matches) >= max_results:
                break
            name = (person.get("name") or "").lower()
            job_title = (person.get("job_title") or "").lower()
            combined = f"{name} {job_title}"
            if any(kw in combined for kw in keywords_lower):
                matches.append(person)
        return matches

    async def _get_page(self, headless: Optional[bool] = None):
        """Get or create a Playwright page"""
        if self.page and not self.page.is_closed():
            return self.page

        if headless is None:
            headless = self.headless

        if not self.playwright_browser:
            self.playwright_browser = await self.session_manager.get_playwright_browser(
                headless=headless
            )

        contexts = self.playwright_browser.contexts
        if contexts:
            context = contexts[0]
        else:
            context = await self.playwright_browser.new_context(
                storage_state=self.session_manager.storage_state_path,
                viewport={"width": 1920, "height": 1080},
            )

        pages = context.pages
        if pages:
            self.page = pages[0]
        else:
            self.page = await context.new_page()

        self.page.on("dialog", lambda dialog: dialog.dismiss())
        return self.page

    async def _extract_linkedin_about_overview(
        self, about_url: str
    ) -> Optional[Dict[str, Any]]:
        """
        Scrape LinkedIn About page and extract Overview section content.

        Returns:
            Dict with keys: description, metadata (dict), full_text, website_url, industry, size
            or None if extraction failed
        """
        try:
            page = await self._get_page()
            logger.info(f"Navigating to LinkedIn About page: {about_url}")

            await page.goto(
                about_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(3)

            # Wait for Overview section
            try:
                await page.wait_for_selector(
                    'section.org-about-module__margin-bottom, h2:has-text("Overview")',
                    timeout=15000,
                )
            except Exception as e:
                logger.warning(f"Overview section not found: {e}")
                return None

            section = page.locator("section.org-about-module__margin-bottom").first
            if await section.count() == 0:
                section = page.locator('h2:has-text("Overview")').locator(
                    "xpath=ancestor::section[1]"
                )

            if await section.count() == 0:
                logger.warning("Could not find Overview section on LinkedIn About page")
                return None

            # Extract description paragraph
            description = ""
            desc_elem = section.locator("p.break-words.white-space-pre-wrap").first
            if await desc_elem.count() > 0:
                description = (await desc_elem.inner_text()).strip()

            # Extract metadata from dl (dt/dd pairs) - use evaluate for reliable parsing
            metadata: Dict[str, str] = {}
            metadata_raw = await section.locator("dl.overflow-hidden").evaluate(
                """
                (dl) => {
                    if (!dl) return {};
                    const pairs = {};
                    const dts = dl.querySelectorAll('dt');
                    const dds = dl.querySelectorAll('dd');
                    let ddIdx = 0;
                    dts.forEach(dt => {
                        const h3 = dt.querySelector('h3');
                        if (h3 && ddIdx < dds.length) {
                            const label = h3.innerText.trim();
                            const value = dds[ddIdx].innerText.trim();
                            if (value.length < 200) pairs[label] = value;
                            ddIdx++;
                            if (label === 'Company size' && ddIdx < dds.length) ddIdx++;
                        }
                    });
                    return pairs;
                }
                """
            )
            if metadata_raw:
                metadata = metadata_raw

            # Build full text
            lines = [description] if description else []
            for k, v in metadata.items():
                if v and k.lower() not in ("verified page",):
                    lines.append(f"{k}: {v}")
            full_text = "\n\n".join(lines)

            # Extract website URL
            website_url = None
            website_link = section.locator('a[href^="http"]').first
            if await website_link.count() > 0:
                href = await website_link.get_attribute("href")
                if href and "linkedin.com" not in href:
                    website_url = href.rstrip(".,;:!?)")

            # Extract industry and size from metadata
            industry = metadata.get("Industry")
            size_raw = metadata.get("Company size") or ""
            size = size_raw.split("\n")[0].strip() if size_raw else None

            return {
                "description": description,
                "metadata": metadata,
                "full_text": full_text,
                "website_url": website_url,
                "industry": industry,
                "size": size,
            }

        except Exception as e:
            logger.error(
                f"Error extracting LinkedIn About overview: {e}",
                exc_info=True,
            )
            return None

    async def _extract_website_content(self, website_url: str) -> Optional[str]:
        """
        Fetch company website and extract main text content.
        """
        try:
            page = await self._get_page()
            logger.info(f"Fetching company website: {website_url}")

            await page.goto(
                website_url,
                wait_until="domcontentloaded",
                timeout=15000,
            )
            await asyncio.sleep(2)

            # Get main content - try main/article first, fallback to body
            content = ""
            for selector in ["main", "article", "[role='main']", "body"]:
                elem = page.locator(selector).first
                if await elem.count() > 0:
                    content = await elem.inner_text()
                    if content and len(content) > 100:
                        break

            if not content:
                content = await page.inner_text("body")

            # Clean and truncate
            content = re.sub(r"\s+", " ", content).strip()
            if len(content) > 5000:
                content = content[:5000] + "..."

            return content if content else None

        except Exception as e:
            logger.warning(f"Could not fetch website content from {website_url}: {e}")
            return None

    async def _extract_people_cards(
        self, section
    ) -> List[Dict[str, Optional[str]]]:
        """Extract people data from cards within the section. Used by _extract_people_you_may_know."""
        people_list: List[Dict[str, Optional[str]]] = []
        cards = section.locator("li.org-people-profile-card__profile-card-spacing")
        card_count = await cards.count()

        for i in range(card_count):
            card = cards.nth(i)
            name = None
            job_title = None
            profile_url = None

            name_elem = card.locator("div.artdeco-entity-lockup__title a")
            if await name_elem.count() > 0:
                name = (await name_elem.inner_text()).strip()

            subtitle_elem = card.locator(
                "div.artdeco-entity-lockup__subtitle .lt-line-clamp"
            )
            if await subtitle_elem.count() > 0:
                job_title = (await subtitle_elem.inner_text()).strip()

            link_elem = card.locator('a[href*="linkedin.com/in/"]').first
            if await link_elem.count() > 0:
                href = await link_elem.get_attribute("href")
                if href:
                    profile_url = href.split("?")[0]

            people_list.append(
                {"name": name, "job_title": job_title, "profile_url": profile_url}
            )

        return people_list

    async def _extract_people_you_may_know(
        self, company_url: str
    ) -> List[Dict[str, Optional[str]]]:
        """
        Scrape the "People you may know" section from a company's LinkedIn People page.
        If "Show more results" button is present, clicks it up to 3 times to load more.

        Args:
            company_url: LinkedIn company page URL

        Returns:
            List of dicts with keys: name, job_title, profile_url
        """
        people_list: List[Dict[str, Optional[str]]] = []
        seen_profile_urls: set = set()

        try:
            page = await self._get_page()
            people_url = self._get_linkedin_people_url(company_url)
            logger.info(f"Navigating to LinkedIn People page: {people_url}")

            await page.goto(
                people_url,
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await asyncio.sleep(3)

            # Wait for "People you may know" section
            try:
                section = page.locator(
                    'div.org-people-profile-card__card-spacing:has(h2:has-text("People you may know"))'
                )
                await section.first.wait_for(state="visible", timeout=15000)
            except Exception as e:
                logger.warning(f"People you may know section not found: {e}")
                return people_list

            show_more_clicked = 0
            max_show_more_clicks = 3

            while True:
                # Re-query section (DOM may have changed after "Show more" click)
                section = page.locator(
                    'div.org-people-profile-card__card-spacing:has(h2:has-text("People you may know"))'
                )
                if await section.count() == 0:
                    break

                # Extract cards and add only new entries (deduplicate by profile_url)
                extracted = await self._extract_people_cards(section)
                for person in extracted:
                    profile_url = person.get("profile_url")
                    if profile_url and profile_url not in seen_profile_urls:
                        seen_profile_urls.add(profile_url)
                        people_list.append(person)

                # Stop if we've already clicked max times
                if show_more_clicked >= max_show_more_clicks:
                    break

                # Look for "Show more results" button
                show_more_btn = section.locator(
                    'button:has-text("Show more results")'
                ).first
                if await show_more_btn.count() == 0 or not await show_more_btn.is_visible():
                    break

                logger.info(
                    f"Clicking 'Show more results' ({show_more_clicked + 1}/{max_show_more_clicks})"
                )
                await show_more_btn.click()
                await asyncio.sleep(5)
                show_more_clicked += 1

            logger.info(
                f"✓ Extracted {len(people_list)} people from People you may know"
            )

        except Exception as e:
            logger.warning(
                f"Could not extract People you may know from {company_url}: {e}",
                exc_info=True,
            )

        return people_list

    async def research_company(self, job: JobListing) -> CompanyResearch:
        """
        Research a company for a given job using Playwright to scrape LinkedIn About page.

        Args:
            job: JobListing object with company information (must have company_url)

        Returns:
            CompanyResearch object with summaries and website URL
        """
        company_name = job.company
        company_url = str(job.company_url) if job.company_url else None

        if not company_url:
            logger.warning(
                f"No company_url found for job {job.job_id}, cannot research company"
            )
            return CompanyResearch(
                job_id=job.job_id or "",
                company_name=company_name,
                recent_news=[],
                tech_stack=[],
            )

        logger.info(f"Researching company: {company_name} using LinkedIn URL: {company_url}")

        try:
            research = CompanyResearch(
                job_id=job.job_id or "",
                company_name=company_name,
                linkedin_url=company_url,
                recent_news=[],
                tech_stack=[],
            )

            # Get About page URL and extract Overview
            about_url = self._get_linkedin_about_url(company_url)
            overview = await self._extract_linkedin_about_overview(about_url)

            if overview:
                research.linkedin_about_summary = overview.get("full_text") or overview.get(
                    "description"
                )
                research.industry = overview.get("industry")
                research.size = overview.get("size")

                if research.linkedin_about_summary:
                    logger.info(
                        f"✓ Extracted LinkedIn About summary ({len(research.linkedin_about_summary)} chars)"
                    )

                # Use same content for linkedin_page_summary (About page is the main source)
                research.linkedin_page_summary = research.linkedin_about_summary

                # Extract and visit company website
                website_url = overview.get("website_url")
                if website_url:
                    try:
                        research.website = website_url
                        logger.info(f"✓ Extracted website URL: {website_url}")

                        website_content = await self._extract_website_content(website_url)
                        if website_content:
                            research.website_summary = website_content
                            logger.info(
                                f"✓ Extracted website summary ({len(website_content)} chars)"
                            )
                    except Exception as e:
                        logger.warning(f"Could not set website URL: {e}")
            else:
                logger.warning("✗ Failed to extract LinkedIn About overview")

            # Scrape People page - "People you may know" section
            people_list = await self._extract_people_you_may_know(company_url)
            key_contacts = self._filter_key_contacts(people_list)
            if key_contacts:
                research.key_contacts = key_contacts
                logger.info(f"✓ Found {len(key_contacts)} key contacts (engineer/HR/hiring)")

            if self.db:
                try:
                    await self.db.save_company_research(job.job_id or "", research)
                    logger.info(f"Saved company research to database for job {job.job_id}")
                except Exception as e:
                    logger.error(f"Error saving research to database: {e}")

            logger.info(f"Completed research for {company_name}")
            return research

        except Exception as e:
            logger.error(
                f"Error researching company {company_name}: {e}",
                exc_info=True,
            )
            return CompanyResearch(
                job_id=job.job_id or "",
                company_name=company_name,
                linkedin_url=company_url,
                recent_news=[],
                tech_stack=[],
            )
