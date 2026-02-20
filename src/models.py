"""Pydantic models for LinkedIn job automation"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl


class JobListing(BaseModel):
    """Job listing model"""
    job_id: Optional[str] = Field(None, description="Unique job identifier (from LinkedIn URL)")
    title: str = Field(..., description="Job title")
    company: str = Field(..., description="Company name")
    url: HttpUrl = Field(..., description="Job posting URL")
    company_url: Optional[HttpUrl] = Field(None, description="LinkedIn company page URL")
    location: Optional[str] = Field(None, description="Job location")
    description: Optional[str] = Field(None, description="Job description")
    posted_date: Optional[datetime] = Field(None, description="Date job was posted")
    skills: Optional[List[str]] = Field(default_factory=list, description="Required skills")
    experience_level: Optional[str] = Field(None, description="Experience level (e.g., Entry, Mid, Senior)")
    job_type: Optional[str] = Field(None, description="Job type (e.g., Full-time, Contract)")
    status: str = Field(default="pending", description="Processing status")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        populate_by_name = True


class CompanyResearch(BaseModel):
    """Company research model"""
    research_id: Optional[str] = Field(None, description="Research identifier")
    job_id: str = Field(..., description="Associated job ID")
    company_name: str = Field(..., description="Company name")
    industry: Optional[str] = Field(None, description="Industry sector")
    size: Optional[str] = Field(None, description="Company size (e.g., 1-10, 11-50, 51-200)")
    recent_news: Optional[List[str]] = Field(default_factory=list, description="Recent news items")
    tech_stack: Optional[List[str]] = Field(default_factory=list, description="Technology stack")
    culture_notes: Optional[str] = Field(None, description="Company culture insights")
    website: Optional[HttpUrl] = Field(None, description="Company website")
    linkedin_url: Optional[HttpUrl] = Field(None, description="LinkedIn company page")
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        populate_by_name = True


class GeneratedMessage(BaseModel):
    """Generated message model"""
    message_id: Optional[str] = Field(None, description="Message identifier")
    job_id: str = Field(..., description="Associated job ID")
    message_text: str = Field(..., description="Generated message content")
    personalization_notes: Optional[str] = Field(None, description="Notes on personalization")
    status: str = Field(default="pending", description="Message status (pending/reviewed/approved)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        populate_by_name = True


class JobPipeline(BaseModel):
    """Complete pipeline result combining job, research, and message"""
    job: JobListing
    research: Optional[CompanyResearch] = None
    message: Optional[GeneratedMessage] = None

    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat()
        }
        populate_by_name = True
