"""Main CLI entry point for LinkedIn automation tool"""

import asyncio
import argparse
from datetime import datetime
from typing import Optional

from src.database import Database
from src.orchestrator import Orchestrator
from src.utils.export import Exporter
from src.utils.logger import logger


async def run_pipeline(
    keywords: str,
    location: Optional[str] = None,
    experience_level: Optional[str] = None,
    job_type: Optional[str] = None,
    max_results: int = 50,
    skip_research: bool = False,
    skip_messages: bool = False
):
    """Run the full automation pipeline"""
    db = Database()
    try:
        await db.connect()
        orchestrator = Orchestrator(db)
        
        pipelines = await orchestrator.run_full_pipeline(
            keywords=keywords,
            location=location,
            experience_level=experience_level,
            job_type=job_type,
            max_results=max_results,
            skip_research=skip_research,
            skip_messages=skip_messages
        )
        
        logger.info(f"Pipeline completed. Processed {len(pipelines)} jobs")
        return pipelines
        
    finally:
        await db.disconnect()


async def export_data(
    output_format: str,
    output_file: Optional[str] = None,
    status: Optional[str] = None,
    company: Optional[str] = None,
    location: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None
):
    """Export data from MongoDB"""
    db = Database()
    try:
        await db.connect()
        exporter = Exporter(db)
        
        # Build filters
        filters = {}
        if status:
            filters['status'] = status
        if company:
            filters['company'] = {'$regex': company, '$options': 'i'}
        if location:
            filters['location'] = {'$regex': location, '$options': 'i'}
        
        # Parse dates
        date_from_obj = None
        date_to_obj = None
        if date_from:
            date_from_obj = datetime.fromisoformat(date_from)
        if date_to:
            date_to_obj = datetime.fromisoformat(date_to)
        
        if date_from_obj or date_to_obj:
            date_filter = {}
            if date_from_obj:
                date_filter['$gte'] = date_from_obj
            if date_to_obj:
                date_filter['$lte'] = date_to_obj
            filters['created_at'] = date_filter
        
        # Query pipelines
        pipelines = await exporter.query_jobs(
            company=company,
            location=location,
            status=status,
            date_from=date_from_obj,
            date_to=date_to_obj
        )
        
        if not pipelines:
            logger.warning("No data found matching filters")
            return
        
        # Export
        if output_format.lower() == 'csv':
            filepath = await exporter.export_to_csv(pipelines=pipelines, filename=output_file)
        else:
            filepath = await exporter.export_to_json(pipelines=pipelines, filename=output_file)
        
        logger.info(f"Exported data to {filepath}")
        
    finally:
        await db.disconnect()


async def list_jobs(
    status: Optional[str] = None,
    limit: int = 20
):
    """List jobs from database"""
    db = Database()
    try:
        await db.connect()
        
        filters = {}
        if status:
            filters['status'] = status
        
        jobs = await db.get_jobs(filters=filters, limit=limit)
        
        if not jobs:
            print("No jobs found.")
            return
        
        print(f"\nFound {len(jobs)} jobs:\n")
        print("-" * 80)
        for job in jobs:
            print(f"Job ID: {job.job_id}")
            print(f"Title: {job.title}")
            print(f"Company: {job.company}")
            print(f"Location: {job.location or 'N/A'}")
            print(f"Status: {job.status}")
            print(f"URL: {job.url}")
            print("-" * 80)
        
    finally:
        await db.disconnect()


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="LinkedIn Job Automation Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline
  python main.py --keywords "software engineer" --location "San Francisco"
  
  # Export pending messages to CSV
  python main.py --export csv --status pending
  
  # Query specific date range
  python main.py --export json --date-from 2025-02-01 --date-to 2025-02-18
  
  # List jobs
  python main.py --list --status pending
        """
    )
    
    # Pipeline arguments
    parser.add_argument('--keywords', type=str, help='Job search keywords')
    parser.add_argument('--location', type=str, help='Location filter')
    parser.add_argument('--experience-level', type=str, choices=['Entry', 'Mid', 'Senior'], help='Experience level')
    parser.add_argument('--job-type', type=str, help='Job type (e.g., Full-time, Contract)')
    parser.add_argument('--max-results', type=int, default=50, help='Maximum number of jobs to scrape')
    parser.add_argument('--skip-research', action='store_true', help='Skip company research phase')
    parser.add_argument('--skip-messages', action='store_true', help='Skip message generation phase')
    
    # Export arguments
    parser.add_argument('--export', type=str, choices=['json', 'csv'], help='Export format')
    parser.add_argument('--output', type=str, help='Output filename')
    parser.add_argument('--status', type=str, help='Filter by status')
    parser.add_argument('--company', type=str, help='Filter by company name')
    parser.add_argument('--date-from', type=str, help='Filter from date (YYYY-MM-DD)')
    parser.add_argument('--date-to', type=str, help='Filter to date (YYYY-MM-DD)')
    
    # List arguments
    parser.add_argument('--list', action='store_true', help='List jobs from database')
    parser.add_argument('--limit', type=int, default=20, help='Limit for list command')
    
    return parser.parse_args()


async def main():
    """Main entry point"""
    args = parse_args()
    
    try:
        # Export mode
        if args.export:
            await export_data(
                output_format=args.export,
                output_file=args.output,
                status=args.status,
                company=args.company,
                location=args.location,
                date_from=args.date_from,
                date_to=args.date_to
            )
        
        # List mode
        elif args.list:
            await list_jobs(status=args.status, limit=args.limit)
        
        # Pipeline mode
        elif args.keywords:
            await run_pipeline(
                keywords=args.keywords,
                location=args.location,
                experience_level=args.experience_level,
                job_type=args.job_type,
                max_results=args.max_results,
                skip_research=args.skip_research,
                skip_messages=args.skip_messages
            )
        
        else:
            print("Error: Please specify --keywords to run pipeline, --export to export data, or --list to list jobs")
            print("Use --help for usage information")
    
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    asyncio.run(main())
