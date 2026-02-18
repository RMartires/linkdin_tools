"""Export utilities for querying MongoDB and exporting to JSON/CSV"""

import json
import csv
from typing import List, Optional, Dict, Any
from datetime import datetime
from pathlib import Path

from src.models import JobPipeline
from src.database import Database
from src.utils.logger import logger


class Exporter:
    """Export data from MongoDB to various formats"""
    
    def __init__(self, db: Database):
        """Initialize exporter with database connection"""
        self.db = db
    
    async def export_to_json(
        self,
        pipelines: Optional[List[JobPipeline]] = None,
        filename: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Export pipelines to JSON file
        
        Args:
            pipelines: List of JobPipeline objects (optional, will query if not provided)
            filename: Output filename (optional, auto-generated if not provided)
            filters: MongoDB filters for querying (if pipelines not provided)
        
        Returns:
            Path to exported file
        """
        if pipelines is None:
            pipelines = await self.db.get_all_pipelines(filters=filters)
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"linkedin_jobs_{timestamp}.json"
        
        # Convert to dict format
        export_data = []
        for pipeline in pipelines:
            data = {
                "job": pipeline.job.model_dump(exclude_none=True),
                "research": pipeline.research.model_dump(exclude_none=True) if pipeline.research else None,
                "message": pipeline.message.model_dump(exclude_none=True) if pipeline.message else None
            }
            export_data.append(data)
        
        # Write to file
        filepath = Path(filename)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(export_data, f, indent=2, default=str, ensure_ascii=False)
        
        logger.info(f"Exported {len(export_data)} pipelines to {filepath}")
        return str(filepath)
    
    async def export_to_csv(
        self,
        pipelines: Optional[List[JobPipeline]] = None,
        filename: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Export pipelines to CSV file
        
        Args:
            pipelines: List of JobPipeline objects (optional, will query if not provided)
            filename: Output filename (optional, auto-generated if not provided)
            filters: MongoDB filters for querying (if pipelines not provided)
        
        Returns:
            Path to exported file
        """
        if pipelines is None:
            pipelines = await self.db.get_all_pipelines(filters=filters)
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"linkedin_jobs_{timestamp}.csv"
        
        # Define CSV columns
        fieldnames = [
            'Job ID',
            'Job Title',
            'Company',
            'Location',
            'Job URL',
            'Posted Date',
            'Status',
            'Industry',
            'Company Size',
            'Recent News',
            'Tech Stack',
            'Message',
            'Message Status',
            'Created At'
        ]
        
        filepath = Path(filename)
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            
            for pipeline in pipelines:
                job = pipeline.job
                research = pipeline.research
                message = pipeline.message
                
                row = {
                    'Job ID': job.job_id or '',
                    'Job Title': job.title,
                    'Company': job.company,
                    'Location': job.location or '',
                    'Job URL': str(job.url),
                    'Posted Date': job.posted_date.isoformat() if job.posted_date else '',
                    'Status': job.status,
                    'Industry': research.industry if research else '',
                    'Company Size': research.size if research else '',
                    'Recent News': '; '.join(research.recent_news[:3]) if research and research.recent_news else '',
                    'Tech Stack': ', '.join(research.tech_stack) if research and research.tech_stack else '',
                    'Message': message.message_text if message else '',
                    'Message Status': message.status if message else '',
                    'Created At': job.created_at.isoformat() if job.created_at else ''
                }
                writer.writerow(row)
        
        logger.info(f"Exported {len(pipelines)} pipelines to {filepath}")
        return str(filepath)
    
    async def query_messages(
        self,
        status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100
    ) -> List[JobPipeline]:
        """Query messages with filters"""
        filters = {}
        
        if status:
            filters['status'] = status
        
        if date_from or date_to:
            date_filter = {}
            if date_from:
                date_filter['$gte'] = date_from
            if date_to:
                date_filter['$lte'] = date_to
            filters['created_at'] = date_filter
        
        return await self.db.get_all_pipelines(filters=filters, limit=limit)
    
    async def query_jobs(
        self,
        company: Optional[str] = None,
        location: Optional[str] = None,
        status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100
    ) -> List[JobPipeline]:
        """Query jobs with filters"""
        filters = {}
        
        if company:
            filters['company'] = {'$regex': company, '$options': 'i'}
        
        if location:
            filters['location'] = {'$regex': location, '$options': 'i'}
        
        if status:
            filters['status'] = status
        
        if date_from or date_to:
            date_filter = {}
            if date_from:
                date_filter['$gte'] = date_from
            if date_to:
                date_filter['$lte'] = date_to
            filters['created_at'] = date_filter
        
        return await self.db.get_all_pipelines(filters=filters, limit=limit)
