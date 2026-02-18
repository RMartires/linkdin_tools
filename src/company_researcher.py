"""Company research module using browser-use"""

import os
from typing import Optional
from browser_use import Agent, ChatOpenAI, Browser
from dotenv import load_dotenv

from src.models import CompanyResearch, JobListing
from src.session_manager import SessionManager
from src.utils.logger import logger

load_dotenv()


class CompanyResearcher:
    """Research companies using browser-use"""
    
    def __init__(self, model: Optional[str] = None, browser: Optional[Browser] = None):
        """Initialize company researcher with OpenRouter LLM
        
        Args:
            model: Optional model name override
            browser: Optional Browser instance (for session persistence)
        """
        model_name = model or os.getenv('MODEL_NAME', 'anthropic/claude-sonnet-4')
        self.llm = ChatOpenAI(
            model=model_name,
            base_url='https://openrouter.ai/api/v1',
            api_key=os.getenv('OPENROUTER_API_KEY'),
        )
        self.browser = browser
        self.session_manager = SessionManager()
    
    async def research_company(self, job: JobListing) -> CompanyResearch:
        """
        Research a company for a given job
        
        Args:
            job: JobListing object with company information
        
        Returns:
            CompanyResearch object
        """
        company_name = job.company
        logger.info(f"Researching company: {company_name}")
        
        task_prompt = f"""
        Research the company "{company_name}" and gather the following information:
        
        1. Find the company's LinkedIn page and extract:
           - Industry sector
           - Company size (number of employees)
           - Company description/about section
           - LinkedIn company page URL
        
        2. Find the company's website and extract:
           - Website URL
           - About page information
           - Company values or culture information
        
        3. Search Google for recent news about "{company_name}" from the last 6 months:
           - Recent news articles or announcements
           - Funding rounds, acquisitions, or major changes
           - Product launches or significant updates
        
        4. If this is a tech role, try to identify:
           - Technology stack used by the company
           - Tech stack mentioned in job descriptions or company pages
        
        Provide comprehensive information about the company.
        """
        
        # Define output schema
        from pydantic import BaseModel, HttpUrl
        from typing import List as TypingList
        
        class CompanyResearchSchema(BaseModel):
            company_name: str
            industry: Optional[str] = None
            size: Optional[str] = None
            recent_news: TypingList[str] = []
            tech_stack: TypingList[str] = []
            culture_notes: Optional[str] = None
            website: Optional[str] = None
            linkedin_url: Optional[str] = None
        
        try:
            # Get browser instance (with session persistence if available)
            browser = self.browser
            if not browser:
                browser = self.session_manager.get_browser(headless=False)
            
            # Create browser-use agent with persistent browser
            agent = Agent(
                task=task_prompt,
                llm=self.llm,
                browser=browser,
                use_vision=False,
            )
            
            # Run agent
            logger.info(f"Running browser-use agent to research {company_name}...")
            history = await agent.run(max_steps=30)
            
            # Extract structured output
            if hasattr(history, 'structured_output') and history.structured_output:
                research_data = history.structured_output
                if isinstance(research_data, dict):
                    pass  # Already a dict
                else:
                    logger.warning("Unexpected structured output format")
                    research_data = {}
            else:
                logger.warning("No structured output found, using defaults")
                research_data = {}
            
            # Create CompanyResearch object
            research = CompanyResearch(
                job_id=job.job_id or "",
                company_name=research_data.get('company_name', company_name),
                industry=research_data.get('industry'),
                size=research_data.get('size'),
                recent_news=research_data.get('recent_news', []),
                tech_stack=research_data.get('tech_stack', []),
                culture_notes=research_data.get('culture_notes'),
                website=research_data.get('website'),
                linkedin_url=research_data.get('linkedin_url')
            )
            
            logger.info(f"Completed research for {company_name}")
            return research
            
        except Exception as e:
            logger.error(f"Error researching company {company_name}: {e}")
            # Return minimal research object on error
            return CompanyResearch(
                job_id=job.job_id or "",
                company_name=company_name,
                recent_news=[],
                tech_stack=[]
            )
