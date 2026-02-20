"""Job scraper stage - scrapes N jobs per day"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Database
from src.job_scraper_playwright import JobScraperPlaywright
from src.utils.logger import logger

load_dotenv()


async def scrape_jobs_stage(max_jobs: int = 50, keywords: str = None, location: str = None):
    """
    Scrape jobs and save to database
    
    Args:
        max_jobs: Maximum number of jobs to scrape
        keywords: Job search keywords (from env if not provided)
        location: Location filter (from env if not provided)
    """
    db = Database()
    scraper = None
    
    try:
        await db.connect()
        logger.info("=" * 60)
        logger.info("Starting job scraping stage")
        logger.info("=" * 60)
        
        # Get search parameters from env or args
        search_keywords = keywords or os.getenv("JOB_KEYWORDS", "software engineer")
        search_location = location or os.getenv("JOB_LOCATION")
        
        logger.info(f"Search parameters: keywords='{search_keywords}', location='{search_location}', max_jobs={max_jobs}")
        
        # Initialize scraper
        scraper = JobScraperPlaywright()
        
        # Scrape jobs
        jobs = await scraper.scrape_jobs(
            keywords=search_keywords,
            location=search_location,
            max_results=max_jobs
        )
        
        if not jobs:
            logger.warning("No jobs found during scraping")
            return 0
        
        logger.info(f"Scraped {len(jobs)} jobs")
        
        # Save to database
        saved_count = await db.save_jobs(jobs)
        
        # Mark jobs as scraped
        for job in jobs:
            if job.job_id:
                await db.mark_job_scraped(job.job_id)
        
        logger.info(f"Successfully saved and marked {saved_count} jobs as 'scraped'")
        logger.info("Job scraping stage completed")
        
        return saved_count
        
    except Exception as e:
        logger.error(f"Error in job scraping stage: {e}", exc_info=True)
        raise
    finally:
        if scraper:
            await scraper.close()
        await db.disconnect()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Scrape jobs stage")
    parser.add_argument("--max-jobs", type=int, default=50, help="Maximum number of jobs to scrape")
    parser.add_argument("--keywords", type=str, help="Job search keywords")
    parser.add_argument("--location", type=str, help="Location filter")
    
    args = parser.parse_args()
    
    asyncio.run(scrape_jobs_stage(
        max_jobs=args.max_jobs,
        keywords=args.keywords,
        location=args.location
    ))
