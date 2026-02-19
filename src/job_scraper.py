"""LinkedIn job scraper using browser-use"""

import os
import re
from typing import List, Optional
from urllib.parse import urlparse, parse_qs
from browser_use import Agent, ChatOpenAI, Browser
from dotenv import load_dotenv

from src.models import JobListing
from src.session_manager import SessionManager
from src.utils.logger import logger

load_dotenv()

# Initialize Laminar for observability (optional - only if API key is set)
lmnr_api_key = os.getenv('LMNR_PROJECT_API_KEY')
if lmnr_api_key:
    try:
        from lmnr import Laminar
        Laminar.initialize(project_api_key=lmnr_api_key)
        logger.info("Laminar observability initialized")
    except ImportError:
        logger.warning("Laminar not installed. Install with: pip install lmnr")
    except Exception as e:
        logger.warning(f"Failed to initialize Laminar: {e}")


class JobScraper:
    """Scrape LinkedIn jobs using browser-use"""
    
    def __init__(self, model: Optional[str] = None, browser: Optional[Browser] = None):
        """Initialize job scraper with OpenRouter LLM
        
        Args:
            model: Optional model name override
            browser: Optional Browser instance (for session persistence)
        """
        model_name = model or os.getenv('MODEL_NAME')
        self.llm = ChatOpenAI(
            model=model_name,
            base_url='https://openrouter.ai/api/v1',
            api_key=os.getenv('OPENROUTER_API_KEY'),
        )
        self.browser = browser
        self.session_manager = SessionManager()
    
    def _extract_job_id(self, url: str) -> Optional[str]:
        """Extract job ID from LinkedIn URL"""
        try:
            # LinkedIn job URLs typically have format: linkedin.com/jobs/view/{job_id}
            match = re.search(r'/jobs/view/(\d+)', url)
            if match:
                return match.group(1)
            # Alternative format: linkedin.com/jobs/collections/{collection_id}/?currentJobId={job_id}
            parsed = urlparse(url)
            query_params = parse_qs(parsed.query)
            if 'currentJobId' in query_params:
                return query_params['currentJobId'][0]
            return None
        except Exception as e:
            logger.warning(f"Could not extract job ID from URL {url}: {e}")
            return None
    
    async def scrape_jobs(
        self,
        keywords: str,
        location: Optional[str] = None,
        experience_level: Optional[str] = None,
        job_type: Optional[str] = None,
        max_results: int = 10
    ) -> List[JobListing]:
        """
        Args:
            keywords: Job search keywords
            location: Location filter (optional)
            experience_level: Experience level filter (optional)
            job_type: Job type filter (optional)
            max_results: Maximum number of jobs to scrape
        
        Returns:
            List of JobListing objects
        """
        logger.info(f"Starting job scrape: keywords='{keywords}', location='{location}'")
        
        # Build search query
        search_query = keywords
        if location:
            search_query += f" in {location}"
        
        linkdin_email = os.getenv('LINKDIN_EMAIL')
        linkdin_password = os.getenv('LINKDIN_PASSWORD')
        # Build task prompt
        task_prompt = f"""
        step 1:
        Goto link: https://www.linkedin.com/

        step 2:
        check if user is already loggedin if not u will see a screen with button "sign in with email"
        if not logged in then:
            click the "sign in with email" button then when we see the login form
            enter and login with these creds: 
                - email: {linkdin_email}
                - password: {linkdin_password}

        else if logged in continue
        Navigate to LinkedIn Jobs at: https://www.linkedin.com/jobs in the same tab 

        step 3:
        wait for page to load fully
        check the component at top left section of the navbar and input for search query: {search_query}

        step 4:
        wait for page to load fully
        now the list loads check for element on the left, this is the list of jobs, 
        this will have a scroll bar to scroll to all the jobs in this page

        step 5:
        wait for page to load fully
        Extract all job listings with the following details:
        - Job title (Required)
        - Company name (Required)
        - Location
        - Posted date (if available)
        
        Scroll through the results to find at least {max_results} jobs.
        Extract as many jobs as possible from the search results.
        """
        
        if experience_level:
            task_prompt += f"\nFilter for experience level: {experience_level}"
        if job_type:
            task_prompt += f"\nFilter for job type: {job_type}"
        
        # Define output schema
        from pydantic import BaseModel, HttpUrl
        from typing import List as TypingList
        
        class JobListingSchema(BaseModel):
            title: str
            company: str
            location: Optional[str] = None
            posted_date: Optional[str] = None        
        class JobListSchema(BaseModel):
            jobs: TypingList[JobListingSchema]
        
        try:
            browser = self.browser
            if not browser:
                browser = self.session_manager.get_browser(headless=False)
            
            # Define observability hooks
            async def on_step_start(agent: Agent):
                """Hook executed at the start of each agent step"""
                try:
                    urls = agent.history.urls()
                    actions = agent.history.model_actions()
                    current_url = await agent.browser_session.get_current_page_url()
                    
                    logger.debug(f"Step {len(urls)} started - Current URL: {current_url}")
                    if actions:
                        logger.debug(f"Last action: {actions[-1]}")
                except Exception as e:
                    logger.debug(f"Error in on_step_start hook: {e}")
            
            async def on_step_end(agent: Agent):
                """Hook executed at the end of each agent step"""
                try:
                    actions = agent.history.model_actions()
                    extracted = agent.history.extracted_content()
                    thoughts = agent.history.model_thoughts()
                    
                    logger.debug(f"Step ended - Actions: {len(actions)}, Extracted items: {len(extracted)}")
                    if thoughts:
                        logger.debug(f"Agent thoughts: {thoughts[-1][:100]}..." if len(thoughts[-1]) > 100 else f"Agent thoughts: {thoughts[-1]}")
                except Exception as e:
                    logger.debug(f"Error in on_step_end hook: {e}")
            
            agent = Agent(
                task=task_prompt,
                llm=self.llm,
                browser=browser,
                use_vision=False,
                calculate_cost=True,  # Enable cost tracking
                output_model_schema=JobListSchema
            )
            
            # Run agent with observability hooks
            logger.info("Running browser-use agent to scrape jobs...")
            history = await agent.run(
                max_steps=50,
                on_step_start=on_step_start,
                on_step_end=on_step_end
            )
            
            # Log final observability stats
            try:
                urls_visited = history.urls() if hasattr(history, 'urls') else []
                actions_taken = history.model_actions() if hasattr(history, 'model_actions') else []
                logger.info(f"Agent execution complete - URLs visited: {len(urls_visited)}, Actions taken: {len(actions_taken)}")
                
                # Log cost if available
                if hasattr(agent, 'token_cost_service'):
                    try:
                        usage_summary = await agent.token_cost_service.get_usage_summary()
                        logger.info(f"Token usage summary: {usage_summary}")
                    except Exception as e:
                        logger.debug(f"Could not get usage summary: {e}")
            except Exception as e:
                logger.debug(f"Error logging observability stats: {e}")
            
            # Extract structured output
            if hasattr(history, 'structured_output') and history.structured_output:
                output = history.structured_output
                if isinstance(output, dict) and 'jobs' in output:
                    jobs_data = output['jobs']
                elif isinstance(output, list):
                    jobs_data = output
                else:
                    jobs_data = []
            else:
                # Fallback: try to extract from final result
                final_result = history.final_result() if hasattr(history, 'final_result') else None
                if final_result:
                    logger.warning("Structured output not available, attempting to parse final result")
                    jobs_data = []
                else:
                    logger.error("No structured output found")
                    jobs_data = []
            
            # Convert to JobListing objects
            job_listings = []
            for job_data in jobs_data[:max_results]:
                try:
                    # Extract job ID from URL
                    job_id = self._extract_job_id(job_data.get('url', ''))
                    
                    # Parse posted_date if it's a string
                    posted_date = None
                    if job_data.get('posted_date'):
                        from datetime import datetime
                        try:
                            posted_date = datetime.fromisoformat(job_data['posted_date'])
                        except:
                            pass
                    
                    job_listing = JobListing(
                        job_id=job_id,
                        title=job_data.get('title', ''),
                        company=job_data.get('company', ''),
                        url=job_data.get('url', ''),
                        location=job_data.get('location'),
                        description=job_data.get('description'),
                        posted_date=posted_date,
                        skills=job_data.get('skills', []),
                        experience_level=job_data.get('experience_level'),
                        job_type=job_data.get('job_type'),
                        status='pending'
                    )
                    job_listings.append(job_listing)
                except Exception as e:
                    logger.error(f"Error creating JobListing from data: {e}")
                    continue
            
            logger.info(f"Successfully scraped {len(job_listings)} jobs")
            return job_listings
            
        except Exception as e:
            logger.error(f"Error scraping jobs: {e}")
            raise
    
    async def scrape_jobs_simple(self, keywords: str, location: Optional[str] = None) -> List[JobListing]:
        """Simplified scraping method"""
        return await self.scrape_jobs(keywords=keywords, location=location)
