"""Test script for DraftGenerator using first job from database"""

import asyncio
from src.database import Database
from src.draft_generator import DraftGenerator
from src.utils.logger import logger


async def test_draft_generator():
    """Test draft generator with first job from database"""
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
        
        # Get company research
        research = await db.get_company_research(job.job_id)
        
        if not research:
            logger.error(f"No company research found for job {job.job_id}. Please run company research first.")
            return
        
        # Check if research has summaries
        has_summaries = any([
            research.linkedin_page_summary,
            research.linkedin_about_summary,
            research.website_summary
        ])
        
        if not has_summaries:
            logger.error("Company research exists but has no summaries. Please ensure research includes at least one summary.")
            logger.info(f"LinkedIn page summary: {bool(research.linkedin_page_summary)}")
            logger.info(f"LinkedIn about summary: {bool(research.linkedin_about_summary)}")
            logger.info(f"Website summary: {bool(research.website_summary)}")
            return
        
        logger.info("Company research found with summaries:")
        if research.linkedin_page_summary:
            logger.info(f"  - LinkedIn page summary: {len(research.linkedin_page_summary)} chars")
        if research.linkedin_about_summary:
            logger.info(f"  - LinkedIn about summary: {len(research.linkedin_about_summary)} chars")
        if research.website_summary:
            logger.info(f"  - Website summary: {len(research.website_summary)} chars")
        
        # Initialize draft generator
        generator = DraftGenerator(db=db)
        
        # Generate draft
        logger.info("\n" + "=" * 80)
        logger.info("Generating cover email draft...")
        logger.info("=" * 80 + "\n")
        
        draft = await generator.generate_draft(job, research)
        
        if not draft:
            logger.error("Failed to generate draft")
            return
        
        # Print results
        logger.info("\n" + "=" * 80)
        logger.info("GENERATED DRAFT")
        logger.info("=" * 80)
        logger.info(f"\nJob: {job.title} at {job.company}")
        logger.info(f"Job ID: {job.job_id}")
        logger.info(f"\nPersonalization Notes: {draft.personalization_notes}")
        logger.info(f"\n--- Email Draft ---\n")
        logger.info(draft.message_text)
        logger.info("\n" + "=" * 80)
        logger.info("Draft generated and saved to database!")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"Error during test: {e}", exc_info=True)
        raise
    
    finally:
        await db.disconnect()
        logger.info("Disconnected from database")


if __name__ == "__main__":
    asyncio.run(test_draft_generator())
