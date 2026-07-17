"""Job scraper stage - thin wrapper around Orchestrator.scrape_jobs"""

import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Database
from src.orchestrator import Orchestrator
from src.utils.logger import logger
from src.utils.config import load_pipeline_config, get_headless_mode

load_dotenv()


async def scrape_jobs_stage(max_jobs: int = 50, keywords: str = None, location: str = None):
    """
    Scrape jobs, save to database, and sync to Google Sheets (via orchestrator).

    Args:
        max_jobs: Maximum number of jobs to scrape
        keywords: Job search keywords (from env if not provided)
        location: Location filter (from env if not provided)
    """
    db = Database()
    orchestrator = None

    try:
        await db.connect()
        logger.info("=" * 60)
        logger.info("Starting job scraping stage")
        logger.info("=" * 60)

        config = load_pipeline_config(Path(__file__).parent / "pipeline_config.yaml")
        headless = get_headless_mode(config)

        search_keywords = keywords or os.getenv("JOB_KEYWORDS", "software engineer")
        search_location = location or os.getenv("JOB_LOCATION")

        logger.info(
            f"Search parameters: keywords='{search_keywords}', location='{search_location}', "
            f"max_jobs={max_jobs}, headless={headless}"
        )

        orchestrator = Orchestrator(db, headless=headless)
        jobs = await orchestrator.scrape_jobs(
            keywords=search_keywords,
            location=search_location,
            max_results=max_jobs,
        )

        if not jobs:
            logger.warning("No jobs found during scraping")
            return 0

        logger.info(f"Job scraping stage completed: {len(jobs)} jobs")
        return len(jobs)

    except Exception as e:
        logger.error(f"Error in job scraping stage: {e}", exc_info=True)
        raise
    finally:
        if orchestrator:
            await orchestrator.close()
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
