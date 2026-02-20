"""Test script for CompanyResearcher using first job from database"""

import asyncio
from src.database import Database
from src.company_researcher import CompanyResearcher
from src.utils.logger import logger


async def test_company_researcher():
    """Test company researcher with first job from database"""
    db = Database()
    
    try:
        # Connect to database
        await db.connect()
        logger.info("Connected to database")
        
        # Get first job from database
        jobs = await db.get_jobs(filters={}, limit=1)
        
        if not jobs:
            logger.error("No jobs found in database. Please scrape some jobs first.")
            return
        
        job = jobs[0]
        logger.info(f"Found job: {job.title} at {job.company}")
        logger.info(f"Job ID: {job.job_id}")
        logger.info(f"Company URL: {job.company_url}")
        
        if not job.company_url:
            logger.error("Job does not have a company_url. Cannot test company research.")
            return
        
        # Initialize company researcher with database
        researcher = CompanyResearcher(db=db)
        
        # Run research
        logger.info("\n" + "=" * 80)
        logger.info("Starting company research...")
        logger.info("=" * 80 + "\n")
        
        research = await researcher.research_company(job)
        
        # Print results
        logger.info("\n" + "=" * 80)
        logger.info("RESEARCH RESULTS")
        logger.info("=" * 80)
        logger.info(f"\nCompany Name: {research.company_name}")
        logger.info(f"Job ID: {research.job_id}")
        logger.info(f"LinkedIn URL: {research.linkedin_url}")
        logger.info(f"Website: {research.website}")
        logger.info(f"\nIndustry: {research.industry or 'N/A'}")
        logger.info(f"Size: {research.size or 'N/A'}")
        
        if research.linkedin_page_summary:
            logger.info(f"\n--- LinkedIn Page Summary ---")
            logger.info(research.linkedin_page_summary)
        
        if research.linkedin_about_summary:
            logger.info(f"\n--- LinkedIn About Summary ---")
            logger.info(research.linkedin_about_summary)
        
        if research.website_summary:
            logger.info(f"\n--- Website Summary ---")
            logger.info(research.website_summary)
        
        if research.recent_news:
            logger.info(f"\n--- Recent News ---")
            for news in research.recent_news:
                logger.info(f"  - {news}")
        
        if research.tech_stack:
            logger.info(f"\n--- Tech Stack ---")
            for tech in research.tech_stack:
                logger.info(f"  - {tech}")
        
        if research.culture_notes:
            logger.info(f"\n--- Culture Notes ---")
            logger.info(research.culture_notes)
        
        logger.info("\n" + "=" * 80)
        logger.info("Research completed and saved to database!")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
        raise
    
    finally:
        await db.disconnect()
        logger.info("Disconnected from database")


if __name__ == "__main__":
    asyncio.run(test_company_researcher())
