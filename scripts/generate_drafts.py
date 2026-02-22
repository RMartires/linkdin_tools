"""Draft generation stage - generates drafts for enriched jobs"""

import asyncio
import os
import sys
import yaml
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Database
from src.draft_generator import DraftGenerator
from src.google_sheets_client import update_draft_in_latest_worksheet
from src.utils.logger import logger

load_dotenv()


async def generate_drafts_stage(batch_size: int = 10, max_retries: int = 3):
    """
    Generate drafts for enriched jobs
    
    Args:
        batch_size: Number of drafts to generate in this run
        max_retries: Maximum retry attempts per job
    """
    db = Database()
    generator = None
    
    try:
        await db.connect()
        logger.info("=" * 60)
        logger.info("Starting draft generation stage")
        logger.info("=" * 60)
        
        # Get jobs ready for generation
        jobs = await db.get_jobs_for_generation(limit=batch_size, max_retries=max_retries)
        
        if not jobs:
            logger.info("No jobs found ready for draft generation")
            return 0
        
        logger.info(f"Found {len(jobs)} jobs ready for draft generation")
        
        # Initialize generator
        generator = DraftGenerator(db=db)
        
        generated_count = 0
        failed_count = 0
        
        for job in jobs:
            try:
                # Update status to "generating"
                await db.update_job_status(job.job_id, "generating")
                logger.info(f"Generating draft for job: {job.title} at {job.company}")
                
                # Get company research
                research = await db.get_company_research(job.job_id)
                
                if not research:
                    error_msg = "No company research found"
                    logger.warning(f"Job {job.job_id}: {error_msg}")
                    await db.increment_generate_retry(job.job_id, error_msg)
                    
                    updated_job = await db.get_job_by_id(job.job_id)
                    if updated_job and updated_job.generate_retry_count >= max_retries:
                        await db.mark_job_failed(job.job_id, "generate", error_msg)
                        failed_count += 1
                    continue
                
                # Generate draft
                draft = await generator.generate_draft(job, research)
                
                if not draft:
                    error_msg = "Draft generation returned None"
                    logger.warning(f"Job {job.job_id}: {error_msg}")
                    await db.increment_generate_retry(job.job_id, error_msg)
                    
                    updated_job = await db.get_job_by_id(job.job_id)
                    if updated_job and updated_job.generate_retry_count >= max_retries:
                        await db.mark_job_failed(job.job_id, "generate", error_msg)
                        failed_count += 1
                    else:
                        # Reset status back to "enriched" for retry
                        await db.update_job_status(job.job_id, "enriched")
                    continue
                
                # Success - update status and clear retry counters
                await db.update_job_status(job.job_id, "draft_generated")
                await db.clear_generate_retry_counters(job.job_id)
                generated_count += 1
                logger.info(f"✓ Successfully generated draft for job {job.job_id}")

                # Google Sheets integration: update draft status in latest worksheet
                config_path = Path(__file__).parent / "pipeline_config.yaml"
                spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
                if config_path.exists() and spreadsheet_id:
                    try:
                        with open(config_path) as f:
                            config = yaml.safe_load(f) or {}
                        if config.get("google_sheets", {}).get("enabled"):
                            await asyncio.to_thread(
                                update_draft_in_latest_worksheet,
                                spreadsheet_id,
                                job.job_id,
                                "Yes",
                            )
                    except Exception as e:
                        logger.warning(f"Google Sheets sync failed (non-fatal): {e}")
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error generating draft for job {job.job_id}: {error_msg}", exc_info=True)
                
                # Increment retry count
                await db.increment_generate_retry(job.job_id, error_msg)
                
                # Check if max retries exceeded
                updated_job = await db.get_job_by_id(job.job_id)
                if updated_job and updated_job.generate_retry_count >= max_retries:
                    await db.mark_job_failed(job.job_id, "generate", error_msg)
                    failed_count += 1
                    logger.error(f"Job {job.job_id} marked as failed after {max_retries} retries")
                else:
                    # Reset status back to "enriched" for retry
                    await db.update_job_status(job.job_id, "enriched")
        
        logger.info(f"Generation stage completed: {generated_count} generated, {failed_count} failed")
        return generated_count
        
    except Exception as e:
        logger.error(f"Error in draft generation stage: {e}", exc_info=True)
        raise
    finally:
        await db.disconnect()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate drafts stage")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of drafts to generate")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum retry attempts")
    
    args = parser.parse_args()
    
    asyncio.run(generate_drafts_stage(
        batch_size=args.batch_size,
        max_retries=args.max_retries
    ))
