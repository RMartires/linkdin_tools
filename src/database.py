"""MongoDB database service for LinkedIn automation"""

import os
from typing import List, Optional, Dict, Any
from datetime import datetime
from pymongo import AsyncMongoClient
from pymongo.errors import DuplicateKeyError
from dotenv import load_dotenv

from src.models import JobListing, CompanyResearch, GeneratedMessage, JobPipeline
from src.utils.logger import logger

load_dotenv()


class Database:
    """MongoDB database service"""
    
    def __init__(self, uri: Optional[str] = None, db_name: Optional[str] = None):
        """Initialize database connection"""
        self.uri = uri or os.getenv("MONGODB_URI", "mongodb://localhost:27017/linkedin_automate")
        self.db_name = db_name or os.getenv("MONGODB_DB_NAME", "linkedin_automate")
        self.client: Optional[AsyncMongoClient] = None
        self.db = None
        
    async def connect(self):
        """Connect to MongoDB"""
        try:
            self.client = AsyncMongoClient(self.uri)
            self.db = self.client[self.db_name]
            # Test connection
            await self.client.admin.command('ping')
            logger.info(f"Connected to MongoDB: {self.db_name}")
            await self._create_indexes()
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            await self.client.close()
            logger.info("Disconnected from MongoDB")
    
    async def _create_indexes(self):
        """Create database indexes for performance"""
        try:
            # Jobs collection indexes
            jobs_collection = self.db.jobs
            await jobs_collection.create_index("job_id", unique=True)
            await jobs_collection.create_index("company")
            await jobs_collection.create_index("location")
            await jobs_collection.create_index("posted_date")
            await jobs_collection.create_index("status")
            
            # Company research collection indexes
            research_collection = self.db.company_research
            await research_collection.create_index("job_id", unique=True)
            await research_collection.create_index("company_name")
            
            # Messages collection indexes
            messages_collection = self.db.messages
            await messages_collection.create_index("job_id", unique=True)
            await messages_collection.create_index("status")
            
            logger.info("Database indexes created successfully")
        except Exception as e:
            logger.warning(f"Error creating indexes: {e}")
    
    # Job operations
    async def save_jobs(self, job_listings: List[JobListing]) -> int:
        """Save or update job listings"""
        saved_count = 0
        for job in job_listings:
            try:
                job_dict = job.model_dump(exclude_none=True)
                job_dict["updated_at"] = datetime.utcnow()
                
                # Try to update existing job, or insert if new
                result = await self.db.jobs.update_one(
                    {"job_id": job.job_id},
                    {"$set": job_dict, "$setOnInsert": {"created_at": datetime.utcnow()}},
                    upsert=True
                )
                if result.upserted_id or result.modified_count > 0:
                    saved_count += 1
            except Exception as e:
                logger.error(f"Error saving job {job.job_id}: {e}")
        
        logger.info(f"Saved {saved_count} jobs to database")
        return saved_count
    
    async def get_jobs(self, filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> List[JobListing]:
        """Get jobs with optional filters"""
        filters = filters or {}
        cursor = self.db.jobs.find(filters).limit(limit)
        jobs = []
        async for doc in cursor:
            # Convert MongoDB document to JobListing
            doc.pop("_id", None)
            jobs.append(JobListing(**doc))
        return jobs
    
    async def get_job_by_id(self, job_id: str) -> Optional[JobListing]:
        """Get a single job by job_id"""
        doc = await self.db.jobs.find_one({"job_id": job_id})
        if doc:
            doc.pop("_id", None)
            return JobListing(**doc)
        return None
    
    async def update_job_status(self, job_id: str, status: str) -> bool:
        """Update job status"""
        result = await self.db.jobs.update_one(
            {"job_id": job_id},
            {"$set": {"status": status, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    # Company research operations
    async def save_company_research(self, job_id: str, research: CompanyResearch) -> bool:
        """Save company research"""
        try:
            research_dict = research.model_dump(exclude_none=True)
            research_dict["job_id"] = job_id
            research_dict["created_at"] = datetime.utcnow()
            
            await self.db.company_research.update_one(
                {"job_id": job_id},
                {"$set": research_dict},
                upsert=True
            )
            logger.info(f"Saved research for job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving research for job {job_id}: {e}")
            return False
    
    async def get_company_research(self, job_id: str) -> Optional[CompanyResearch]:
        """Get company research for a job"""
        doc = await self.db.company_research.find_one({"job_id": job_id})
        if doc:
            doc.pop("_id", None)
            return CompanyResearch(**doc)
        return None
    
    # Message operations
    async def save_message(self, job_id: str, message: GeneratedMessage) -> bool:
        """Save generated message"""
        try:
            message_dict = message.model_dump(exclude_none=True)
            message_dict["job_id"] = job_id
            message_dict["updated_at"] = datetime.utcnow()
            
            await self.db.messages.update_one(
                {"job_id": job_id},
                {"$set": message_dict, "$setOnInsert": {"created_at": datetime.utcnow()}},
                upsert=True
            )
            logger.info(f"Saved message for job {job_id}")
            return True
        except Exception as e:
            logger.error(f"Error saving message for job {job_id}: {e}")
            return False
    
    async def get_message(self, job_id: str) -> Optional[GeneratedMessage]:
        """Get message for a job"""
        doc = await self.db.messages.find_one({"job_id": job_id})
        if doc:
            doc.pop("_id", None)
            return GeneratedMessage(**doc)
        return None
    
    async def update_message_status(self, job_id: str, status: str) -> bool:
        """Update message status"""
        result = await self.db.messages.update_one(
            {"job_id": job_id},
            {"$set": {"status": status, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0
    
    async def get_pending_messages(self, limit: int = 100) -> List[GeneratedMessage]:
        """Get messages pending review"""
        cursor = self.db.messages.find({"status": "pending"}).limit(limit)
        messages = []
        async for doc in cursor:
            doc.pop("_id", None)
            messages.append(GeneratedMessage(**doc))
        return messages
    
    # Pipeline operations
    async def get_job_pipeline(self, job_id: str) -> Optional[JobPipeline]:
        """Get complete pipeline (job + research + message)"""
        job = await self.get_job_by_id(job_id)
        if not job:
            return None
        
        research = await self.get_company_research(job_id)
        message = await self.get_message(job_id)
        
        return JobPipeline(job=job, research=research, message=message)
    
    async def get_all_pipelines(self, filters: Optional[Dict[str, Any]] = None, limit: int = 100) -> List[JobPipeline]:
        """Get all complete pipelines"""
        jobs = await self.get_jobs(filters, limit)
        pipelines = []
        for job in jobs:
            research = await self.get_company_research(job.job_id)
            message = await self.get_message(job.job_id)
            pipelines.append(JobPipeline(job=job, research=research, message=message))
        return pipelines
