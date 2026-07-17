"""Workflow orchestrator for LinkedIn job automation"""

import asyncio
import os
from typing import List, Optional, Dict, Any

from src.database import Database
from src.job_scraper_playwright import JobScraperPlaywright
from src.company_researcher_playwright import CompanyResearcherPlaywright
from src.draft_generator import DraftGenerator
from src.template_draft_generator import TemplateDraftGenerator
from src.session_manager import SessionManager
from src.models import JobListing, CompanyResearch, GeneratedMessage, JobPipeline
from src.google_sheets_client import upsert_jobs, update_job_message, _format_date_scraped
from src.utils.config import load_pipeline_config, get_use_template_mode
from src.utils.logger import logger


class Orchestrator:
    """Orchestrates the full LinkedIn automation pipeline"""

    def __init__(self, db: Database, model: Optional[str] = None, headless: bool = False):
        """Initialize orchestrator with database connection

        Args:
            db: Database instance
            model: Optional model name to override MODEL_NAME env var
            headless: Run browser headless (from pipeline config for daemon runs)
        """
        self.db = db
        self.model = model
        self.headless = headless
        self.session_manager = SessionManager()

        # Single shared CDP session for scrape + research (avoid profile lock races)
        self.playwright_browser = None
        self.job_scraper = JobScraperPlaywright(
            model=model,
            browser=None,
            session_manager=self.session_manager,
        )
        self.company_researcher = CompanyResearcherPlaywright(
            db=db,
            session_manager=self.session_manager,
            headless=headless,
        )

    async def _ensure_playwright_browser(self):
        """Ensure persistent LinkedIn profile context is ready and authenticated"""
        if not self.playwright_browser:
            page = await self.session_manager.get_page(headless=self.headless)
            await self.session_manager.assert_logged_in(page)
            self.playwright_browser = await self.session_manager.get_playwright_browser(
                headless=self.headless
            )
            self.job_scraper.playwright_browser = self.playwright_browser
            self.company_researcher.playwright_browser = self.playwright_browser

    async def close(self):
        """Release Chrome/CDP resources"""
        try:
            await self.session_manager.close()
        except Exception as e:
            logger.debug(f"session_manager.close error: {e}")
        self.playwright_browser = None

    # --- Google Sheets sync (non-fatal) ---

    @staticmethod
    def _sheets_spreadsheet_id() -> Optional[str]:
        """Return spreadsheet ID if Sheets sync is enabled, else None."""
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        if not spreadsheet_id:
            return None
        config = load_pipeline_config()
        if not config.get("google_sheets", {}).get("enabled"):
            return None
        return spreadsheet_id

    async def _sync_jobs_to_sheets(self, jobs: List[JobListing], search_query: str):
        spreadsheet_id = self._sheets_spreadsheet_id()
        if not spreadsheet_id:
            return
        try:
            await asyncio.to_thread(upsert_jobs, spreadsheet_id, jobs, search_query)
        except Exception as e:
            logger.warning(f"Google Sheets job sync failed (non-fatal): {e}")

    async def _sync_message_to_sheets(self, job: JobListing, message: GeneratedMessage):
        spreadsheet_id = self._sheets_spreadsheet_id()
        if not spreadsheet_id:
            return
        try:
            await asyncio.to_thread(
                update_job_message,
                spreadsheet_id,
                job.job_id,
                message.message_text,
                message.personalized_drafts,
                "draft_generated",
                _format_date_scraped(job),
            )
        except Exception as e:
            logger.warning(f"Google Sheets message sync failed (non-fatal): {e}")

    async def scrape_jobs(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience_level: Optional[str] = None,
        job_type: Optional[str] = None,
        max_results: int = 50,
    ) -> List[JobListing]:
        """Scrape jobs and save to database"""
        logger.info("Starting job scraping phase...")

        await self._ensure_playwright_browser()

        jobs = await self.job_scraper.scrape_jobs(
            keywords=keywords,
            location=location,
            experience_level=experience_level,
            job_type=job_type,
            max_results=max_results,
        )

        if jobs:
            await self.db.save_jobs(jobs)
            for job in jobs:
                if job.job_id:
                    await self.db.mark_job_scraped(job.job_id)
            logger.info(f"Saved {len(jobs)} jobs to database")

            search_query = f"{keywords} ({location})" if location else keywords
            await self._sync_jobs_to_sheets(jobs, search_query)

        return jobs

    async def research_companies(
        self,
        jobs: Optional[List[JobListing]] = None,
        job_ids: Optional[List[str]] = None,
        batch_size: int = 1,
    ) -> Dict[str, CompanyResearch]:
        """Research companies for jobs (sequential by default — shared Playwright page)."""
        logger.info("Starting company research phase...")

        if not jobs:
            if job_ids:
                jobs = []
                for job_id in job_ids:
                    job = await self.db.get_job_by_id(job_id)
                    if job:
                        jobs.append(job)
            else:
                jobs = await self.db.get_jobs_for_enrichment(limit=100)
                if not jobs:
                    jobs = await self.db.get_jobs({"status": "pending"}, limit=100)

        if not jobs:
            logger.warning("No jobs found for research")
            return {}

        await self._ensure_playwright_browser()

        for i, job in enumerate(jobs):
            try:
                before = (job.location, job.description, str(job.company_url or ""))
                jobs[i] = await self.job_scraper.backfill_job_details(job)
                if (jobs[i].location, jobs[i].description, str(jobs[i].company_url or "")) != before:
                    await self.db.save_jobs([jobs[i]])
            except Exception as e:
                logger.warning(f"Job detail backfill failed for {job.job_id}: {e}")

        logger.info(f"Researching {len(jobs)} companies...")
        research_results: Dict[str, CompanyResearch] = {}

        for i in range(0, len(jobs), batch_size):
            batch = jobs[i : i + batch_size]
            logger.info(f"Processing research batch {i // batch_size + 1} ({len(batch)} companies)")

            for job in batch:
                try:
                    result = await self._research_single_company(job)
                    if result and self._research_has_content(result):
                        research_results[job.job_id] = result
                        await self.db.save_company_research(job.job_id, result)
                        await self.db.update_job_status(job.job_id, "enriched")
                        logger.info(f"✓ Research saved for {job.company} (job {job.job_id})")
                    else:
                        logger.error(
                            f"Research for {job.company} produced empty content; continuing"
                        )
                except Exception as e:
                    logger.error(f"Error researching {job.company}: {e}", exc_info=True)

            if i + batch_size < len(jobs):
                await asyncio.sleep(1)

        logger.info(f"Completed research for {len(research_results)} companies")
        return research_results

    @staticmethod
    def _research_has_content(research: CompanyResearch) -> bool:
        return any(
            (
                research.linkedin_page_summary,
                research.linkedin_about_summary,
                research.website_summary,
            )
        )

    async def _research_single_company(self, job: JobListing) -> Optional[CompanyResearch]:
        """Research a single company, reusing existing named research when present."""
        try:
            existing = await self.db.get_company_research_by_name(job.company)
            if existing and self._research_has_content(existing):
                logger.info(
                    f"Reusing existing research for {job.company} on job {job.job_id}"
                )
                return existing.model_copy(update={"job_id": job.job_id or ""})

            return await self.company_researcher.research_company(job)
        except Exception as e:
            logger.error(f"Error researching company {job.company}: {e}", exc_info=True)
            return None

    async def generate_messages(
        self,
        jobs: Optional[List[JobListing]] = None,
        job_ids: Optional[List[str]] = None,
    ) -> Dict[str, GeneratedMessage]:
        """Generate drafts for jobs.

        Template mode needs no company research (works straight from scraped jobs);
        AI mode still requires usable research.
        """
        logger.info("Starting message generation phase...")

        use_template = get_use_template_mode()

        if not jobs:
            if job_ids:
                jobs = []
                for job_id in job_ids:
                    job = await self.db.get_job_by_id(job_id)
                    if job:
                        jobs.append(job)
            else:
                statuses = ["scraped", "enriched"] if use_template else ["enriched"]
                jobs = await self.db.get_jobs_for_generation(limit=100, statuses=statuses)

        if not jobs:
            logger.warning("No jobs found for message generation")
            return {}

        if use_template:
            logger.info("Using TemplateDraftGenerator (template mode, no AI)")
            generator = TemplateDraftGenerator()
        else:
            logger.info("Using DraftGenerator (OpenRouter AI mode)")
            generator = DraftGenerator(db=self.db, model=self.model)

        logger.info(f"Generating messages for {len(jobs)} jobs...")
        message_results: Dict[str, GeneratedMessage] = {}

        for job in jobs:
            try:
                research = await self.db.get_company_research(job.job_id)
                if not research:
                    research = await self.db.get_company_research_by_name(job.company)

                if not use_template and (
                    not research or not self._research_has_content(research)
                ):
                    logger.warning(
                        f"Skipping message for job {job.job_id}: no usable research"
                    )
                    continue

                message = await generator.generate_draft(job, research)
                if not message or not (message.message_text or "").strip():
                    logger.error(f"Empty draft for job {job.job_id}; skipping")
                    continue

                message_results[job.job_id] = message
                await self.db.save_message(job.job_id, message)
                await self.db.update_job_status(job.job_id, "draft_generated")
                await self.db.clear_generate_retry_counters(job.job_id)
                await self._sync_message_to_sheets(job, message)
                logger.info(
                    f"✓ Draft saved for {job.company} ({len(message.message_text)} chars)"
                )
            except Exception as e:
                logger.error(
                    f"Error generating message for job {job.job_id}: {e}",
                    exc_info=True,
                )

        logger.info(f"Generated {len(message_results)} messages")
        return message_results

    async def run_full_pipeline(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience_level: Optional[str] = None,
        job_type: Optional[str] = None,
        max_results: int = 50,
        skip_research: bool = True,
        skip_messages: bool = False,
    ) -> List[JobPipeline]:
        """Run scrape -> (optional research) -> message generation."""
        logger.info("=" * 60)
        logger.info("Starting full LinkedIn automation pipeline")
        logger.info("=" * 60)

        try:
            jobs = await self.scrape_jobs(
                keywords=keywords,
                location=location,
                experience_level=experience_level,
                job_type=job_type,
                max_results=max_results,
            )

            if not jobs:
                logger.warning("No jobs found. Pipeline stopped.")
                return []

            logger.info(f"Scraped and saved {len(jobs)} jobs")

            research_results: Dict[str, CompanyResearch] = {}
            if not skip_research:
                research_results = await self.research_companies(jobs=jobs)
            else:
                logger.info("Skipping company research phase")

            message_results: Dict[str, GeneratedMessage] = {}
            if not skip_messages:
                message_results = await self.generate_messages(jobs=jobs)
            else:
                logger.info("Skipping message generation phase")

            pipelines = [
                JobPipeline(
                    job=job,
                    research=research_results.get(job.job_id),
                    message=message_results.get(job.job_id),
                )
                for job in jobs
            ]

            logger.info("=" * 60)
            logger.info(f"Pipeline completed. Processed {len(pipelines)} jobs")
            logger.info(
                f"Research ok={sum(1 for p in pipelines if p.research)} "
                f"Messages ok={sum(1 for p in pipelines if p.message)}"
            )
            logger.info("=" * 60)
            return pipelines
        finally:
            await self.close()

    async def get_pipelines(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> List[JobPipeline]:
        """Get pipelines from database"""
        return await self.db.get_all_pipelines(filters=filters, limit=limit)
