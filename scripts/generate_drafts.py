"""Draft generation stage - thin wrapper around Orchestrator.generate_messages"""

import asyncio
import sys
from pathlib import Path
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.database import Database
from src.orchestrator import Orchestrator
from src.utils.logger import logger
from src.utils.config import get_use_template_mode

load_dotenv()


async def generate_drafts_stage(batch_size: int = 10, max_retries: int = 3):
    """
    Generate drafts for jobs (template mode works straight from scraped jobs).

    Args:
        batch_size: Number of drafts to generate in this run
        max_retries: Maximum retry attempts per job
    """
    db = Database()

    try:
        await db.connect()
        logger.info("=" * 60)
        logger.info("Starting draft generation stage")
        logger.info("=" * 60)

        use_template = get_use_template_mode()
        statuses = ["scraped", "enriched"] if use_template else ["enriched"]
        jobs = await db.get_jobs_for_generation(
            limit=batch_size, max_retries=max_retries, statuses=statuses
        )

        if not jobs:
            logger.info("No jobs found ready for draft generation")
            return 0

        logger.info(f"Found {len(jobs)} jobs ready for draft generation")

        orchestrator = Orchestrator(db)
        results = await orchestrator.generate_messages(jobs=jobs)

        # Retry bookkeeping for jobs that produced no draft
        failed_count = 0
        for job in jobs:
            if job.job_id in results:
                continue
            error_msg = job.generate_error or "Draft generation produced no message"
            await db.increment_generate_retry(job.job_id, error_msg)
            updated_job = await db.get_job_by_id(job.job_id)
            if updated_job and updated_job.generate_retry_count >= max_retries:
                await db.mark_job_failed(job.job_id, "generate", error_msg)
                failed_count += 1
                logger.error(f"Job {job.job_id} marked as failed after {max_retries} retries")

        logger.info(
            f"Generation stage completed: {len(results)} generated, {failed_count} failed"
        )
        return len(results)

    except Exception as e:
        logger.error(f"Error in draft generation stage: {e}", exc_info=True)
        raise
    finally:
        await db.disconnect()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate LinkedIn DM drafts for jobs")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of drafts to generate")
    parser.add_argument("--max-retries", type=int, default=3, help="Maximum retry attempts")

    args = parser.parse_args()

    asyncio.run(generate_drafts_stage(
        batch_size=args.batch_size,
        max_retries=args.max_retries
    ))
