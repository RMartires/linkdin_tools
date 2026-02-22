"""Workflow orchestrator for LinkedIn job automation"""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

from src.database import Database
from src.job_scraper import JobScraper
from src.job_scraper_playwright import JobScraperPlaywright
from src.company_researcher import CompanyResearcher
from src.session_manager import SessionManager
from src.models import JobListing, CompanyResearch, GeneratedMessage, JobPipeline
from src.utils.logger import logger


class Orchestrator:
    """Orchestrates the full LinkedIn automation pipeline"""
    
    def __init__(self, db: Database, model: Optional[str] = None):
        """Initialize orchestrator with database connection
        
        Args:
            db: Database instance
            model: Optional model name to override MODEL_NAME env var
        """
        self.db = db
        self.model = model
        self.session_manager = SessionManager()
        
        # Defer browser-use creation - it launches Chrome and conflicts with Playwright
        # when both try to use the same profile. Only create when research phase runs.
        self.browser = None  # Lazy init in research_companies
        self.playwright_browser = None  # Will be initialized async in scrape_jobs
        
        # Use Playwright scraper (doesn't need browser-use)
        self.job_scraper = JobScraperPlaywright(model=model, browser=None)
        self.company_researcher = CompanyResearcher(model=model, browser=None, db=db)
    
    async def _ensure_playwright_browser(self):
        """Ensure Playwright browser is initialized"""
        if not self.playwright_browser:
            self.playwright_browser = await self.session_manager.get_playwright_browser(headless=False)
            self.job_scraper.playwright_browser = self.playwright_browser
    
    async def scrape_jobs(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience_level: Optional[str] = None,
        job_type: Optional[str] = None,
        max_results: int = 50
    ) -> List[JobListing]:
        """
        Scrape jobs and save to database
        
        Returns:
            List of JobListing objects
        """
        logger.info("Starting job scraping phase...")
        
        # Ensure Playwright browser is initialized before scraping
        await self._ensure_playwright_browser()
        
        # Scrape jobs
        jobs = await self.job_scraper.scrape_jobs(
            keywords=keywords,
            location=location,
            experience_level=experience_level,
            job_type=job_type,
            max_results=max_results
        )
        
        # Save to database
        if jobs:
            await self.db.save_jobs(jobs)
            logger.info(f"Saved {len(jobs)} jobs to database")
        
        return jobs
    
    async def research_companies(
        self,
        jobs: Optional[List[JobListing]] = None,
        job_ids: Optional[List[str]] = None,
        batch_size: int = 5
    ) -> Dict[str, CompanyResearch]:
        """
        Research companies for jobs
        
        Args:
            jobs: List of JobListing objects (optional)
            job_ids: List of job IDs to research (optional)
            batch_size: Number of companies to research in parallel
        
        Returns:
            Dictionary mapping job_id to CompanyResearch
        """
        logger.info("Starting company research phase...")
        
        # Get jobs if not provided
        if not jobs:
            if job_ids:
                jobs = []
                for job_id in job_ids:
                    job = await self.db.get_job_by_id(job_id)
                    if job:
                        jobs.append(job)
            else:
                # Get all pending jobs
                jobs = await self.db.get_jobs({"status": "pending"}, limit=100)
        
        if not jobs:
            logger.warning("No jobs found for research")
            return {}
        
        logger.info(f"Researching {len(jobs)} companies...")
        
        # Process in batches to avoid overwhelming the system
        research_results = {}
        
        for i in range(0, len(jobs), batch_size):
            batch = jobs[i:i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1} ({len(batch)} companies)")
            
            # Process batch concurrently
            tasks = [self._research_single_company(job) for job in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for job, result in zip(batch, batch_results):
                if isinstance(result, Exception):
                    logger.error(f"Error researching {job.company}: {result}")
                elif result:
                    research_results[job.job_id] = result
                    await self.db.save_company_research(job.job_id, result)
            
            # Small delay between batches
            if i + batch_size < len(jobs):
                await asyncio.sleep(2)
        
        logger.info(f"Completed research for {len(research_results)} companies")
        return research_results
    
    def _ensure_browser_use_browser(self):
        """Lazy init browser-use browser (only needed for company research)"""
        if self.browser is None:
            self.browser = self.session_manager.get_browser(headless=False)
            self.company_researcher.browser = self.browser
            logger.info("Created browser-use browser for company research")
    
    async def _research_single_company(self, job: JobListing) -> Optional[CompanyResearch]:
        """Research a single company"""
        try:
            self._ensure_browser_use_browser()
            research = await self.company_researcher.research_company(job)
            return research
        except Exception as e:
            logger.error(f"Error researching company {job.company}: {e}")
            return None
    
    
    async def run_full_pipeline(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience_level: Optional[str] = None,
        job_type: Optional[str] = None,
        max_results: int = 50,
        skip_research: bool = False,
        skip_messages: bool = False
    ) -> List[JobPipeline]:
        """
        Run the complete pipeline: scrape -> research -> generate messages
        
        Args:
            keywords: Job search keywords
            location: Location filter
            experience_level: Experience level filter
            job_type: Job type filter
            max_results: Maximum number of jobs
            skip_research: Skip company research phase
            skip_messages: Skip message generation phase
        
        Returns:
            List of JobPipeline objects
        """
        logger.info("=" * 60)
        logger.info("Starting full LinkedIn automation pipeline")
        logger.info("=" * 60)
        
        # Phase 1: Scrape jobs
        jobs = await self.scrape_jobs(
            keywords=keywords,
            location=location,
            experience_level=experience_level,
            job_type=job_type,
            max_results=max_results
        )
        
        if not jobs:
            logger.warning("No jobs found. Pipeline stopped.")
            return []
        logger.info(jobs)
        return []