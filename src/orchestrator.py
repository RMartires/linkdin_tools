"""Workflow orchestrator for LinkedIn job automation"""

import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime

from src.database import Database
from src.job_scraper import JobScraper
from src.job_scraper_playwright import JobScraperPlaywright
from src.company_researcher import CompanyResearcher
from src.message_generator import MessageGenerator
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
        
        # Create shared browser instances for session persistence
        # JobScraperPlaywright uses Playwright, CompanyResearcher uses browser-use (for now)
        self.browser = self.session_manager.get_browser(headless=False)  # For CompanyResearcher
        self.playwright_browser = None  # Will be initialized async
        
        # Use Playwright scraper instead of browser-use scraper
        self.job_scraper = JobScraperPlaywright(model=model, browser=self.browser)  # Will set playwright_browser async
        self.company_researcher = CompanyResearcher(model=model, browser=self.browser, db=db)
        self.message_generator = MessageGenerator(model=model)
    
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
    
    async def _research_single_company(self, job: JobListing) -> Optional[CompanyResearch]:
        """Research a single company"""
        try:
            research = await self.company_researcher.research_company(job)
            return research
        except Exception as e:
            logger.error(f"Error researching company {job.company}: {e}")
            return None
    
    async def generate_messages(
        self,
        jobs: Optional[List[JobListing]] = None,
        job_ids: Optional[List[str]] = None
    ) -> Dict[str, GeneratedMessage]:
        """
        Generate messages for jobs
        
        Args:
            jobs: List of JobListing objects (optional)
            job_ids: List of job IDs to generate messages for (optional)
        
        Returns:
            Dictionary mapping job_id to GeneratedMessage
        """
        logger.info("Starting message generation phase...")
        
        # Get jobs if not provided
        if not jobs:
            if job_ids:
                jobs = []
                for job_id in job_ids:
                    job = await self.db.get_job_by_id(job_id)
                    if job:
                        jobs.append(job)
            else:
                # Get jobs that have research but no message yet
                jobs = await self.db.get_jobs({"status": "pending"}, limit=100)
        
        if not jobs:
            logger.warning("No jobs found for message generation")
            return {}
        
        logger.info(f"Generating messages for {len(jobs)} jobs...")
        
        message_results = {}
        
        for job in jobs:
            try:
                # Get research if available
                research = await self.db.get_company_research(job.job_id)
                
                # Generate message
                message = await self.message_generator.generate_message(job, research)
                message_results[job.job_id] = message
                
                # Save to database
                await self.db.save_message(job.job_id, message)
                
                # Update job status
                await self.db.update_job_status(job.job_id, "message_generated")
                
            except Exception as e:
                logger.error(f"Error generating message for job {job.job_id}: {e}")
        
        logger.info(f"Generated {len(message_results)} messages")
        return message_results
    
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

        # Phase 2: Research companies
        research_results = {}
        if not skip_research:
            research_results = await self.research_companies(jobs=jobs)
        else:
            logger.info("Skipping company research phase")
        
        # Phase 3: Generate messages
        message_results = {}
        if not skip_messages:
            message_results = await self.generate_messages(jobs=jobs)
        else:
            logger.info("Skipping message generation phase")
        
        # Build pipeline results
        pipelines = []
        for job in jobs:
            research = research_results.get(job.job_id)
            message = message_results.get(job.job_id)
            pipelines.append(JobPipeline(job=job, research=research, message=message))
        
        logger.info("=" * 60)
        logger.info(f"Pipeline completed. Processed {len(pipelines)} jobs")
        logger.info("=" * 60)
        
        return pipelines
    
    async def get_pipelines(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> List[JobPipeline]:
        """Get pipelines from database"""
        return await self.db.get_all_pipelines(filters=filters, limit=limit)
