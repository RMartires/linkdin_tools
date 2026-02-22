"""Company enrichment stage - enriches scraped jobs"""

import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Database
from src.company_researcher import CompanyResearcher
from src.models import CompanyResearch
from src.utils.logger import logger
from src.utils.config import load_pipeline_config, get_headless_mode

load_dotenv()


async def enrich_companies_stage(batch_size: int = 10, max_retries: int = 3):
    """
    Enrich companies for scraped jobs
    
    Args:
        batch_size: Number of companies to process in this run
        max_retries: Maximum retry attempts per job
    """
    db = Database()
    researcher = None
    
    try:
        await db.connect()
        logger.info("=" * 60)
        logger.info("Starting company enrichment stage")
        logger.info("=" * 60)
        
        # Load config and get headless mode
        config_path = Path(__file__).parent / "pipeline_config.yaml"
        config = load_pipeline_config(config_path)
        headless = get_headless_mode(config)
        
        logger.info(f"Browser headless mode: {headless}")
        
        # Get jobs ready for enrichment
        jobs = await db.get_jobs_for_enrichment(limit=batch_size, max_retries=max_retries)
        
        if not jobs:
            logger.info("No jobs found ready for enrichment")
            return 0
        
        logger.info(f"Found {len(jobs)} jobs ready for enrichment")
        
        # Initialize researcher with headless flag
        researcher = CompanyResearcher(db=db, headless=headless)
        
        enriched_count = 0
        failed_count = 0
        
        for job in jobs:
            try:
                # Update status to "enriching"
                await db.update_job_status(job.job_id, "enriching")
                logger.info(f"Enriching company for job: {job.title} at {job.company}")
                
                # Check if company research already exists
                existing_research = await db.get_company_research_by_name(job.company)
                if existing_research and (existing_research.linkedin_about_summary or existing_research.linkedin_page_summary):
                    logger.info(f"Company research already exists for {job.company} with summaries. Reusing existing research for job {job.job_id}")
                    # Copy existing research and update job_id
                    research = CompanyResearch(
                        job_id=job.job_id,
                        company_name=existing_research.company_name,
                        industry=existing_research.industry,
                        size=existing_research.size,
                        recent_news=existing_research.recent_news or [],
                        tech_stack=existing_research.tech_stack or [],
                        culture_notes=existing_research.culture_notes,
                        website=existing_research.website,
                        linkedin_url=existing_research.linkedin_url,
                        linkedin_page_summary=existing_research.linkedin_page_summary,
                        linkedin_about_summary=existing_research.linkedin_about_summary,
                        website_summary=existing_research.website_summary,
                        created_at=existing_research.created_at
                    )
                    # Save with new job_id
                    await db.save_company_research(job.job_id, research)
                else:
                    # Research company
                    research = await researcher.research_company(job)
                
                # Check if research has at least one summary (required for next stage)
                if not any([
                    research.linkedin_page_summary,
                    research.linkedin_about_summary,
                    research.website_summary
                ]):
                    error_msg = "Research completed but no summaries available"
                    logger.warning(f"Job {job.job_id}: {error_msg}")
                    
                    # Increment retry count
                    await db.increment_enrich_retry(job.job_id, error_msg)
                    
                    # Check if max retries exceeded
                    updated_job = await db.get_job_by_id(job.job_id)
                    if updated_job and updated_job.enrich_retry_count >= max_retries:
                        await db.mark_job_failed(job.job_id, "enrich", error_msg)
                        failed_count += 1
                        logger.error(f"Job {job.job_id} marked as failed after {max_retries} retries")
                    continue
                
                # Success - update status and clear retry counters
                await db.update_job_status(job.job_id, "enriched")
                await db.clear_enrich_retry_counters(job.job_id)
                enriched_count += 1
                logger.info(f"✓ Successfully enriched company for job {job.job_id}")
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error enriching company for job {job.job_id}: {error_msg}", exc_info=True)
                
                # Increment retry count
                await db.increment_enrich_retry(job.job_id, error_msg)
                
                # Check if max retries exceeded
                updated_job = await db.get_job_by_id(job.job_id)
                if updated_job and updated_job.enrich_retry_count >= max_retries:
                    await db.mark_job_failed(job.job_id, "enrich", error_msg)
                    failed_count += 1
                    logger.error(f"Job {job.job_id} marked as failed after {max_retries} retries")
                else:
                    # Reset status back to "scraped" for retry
                    await db.update_job_status(job.job_id, "scraped")
        
        logger.info(f"Enrichment stage completed: {enriched_count} enriched, {failed_count} failed")
        return enriched_count
        
    except Exception as e:
        logger.error(f"Error in company enrichment stage: {e}", exc_info=True)
        raise
    finally:
        await db.disconnect()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Enrich companies stage")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of companies to process")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum retry attempts")
    
    args = parser.parse_args()
    
    asyncio.run(enrich_companies_stage(
        batch_size=args.batch_size,
        max_retries=args.max_retries
    ))
