"""Company research module using browser-use"""

import os
import re
from typing import Optional
from pydantic import BaseModel
from browser_use import Agent, ChatOpenAI, Browser
from dotenv import load_dotenv

from src.models import CompanyResearch, JobListing
from src.database import Database
from src.session_manager import SessionManager
from src.utils.logger import logger

load_dotenv()


class CompanyResearcher:
    """Research companies using browser-use"""
    
    def __init__(self, model: Optional[str] = None, browser: Optional[Browser] = None, db: Optional[Database] = None, headless: bool = False):
        """Initialize company researcher with OpenRouter LLM
        
        Args:
            model: Optional model name override
            browser: Optional Browser instance (for session persistence)
            db: Optional Database instance for saving research
            headless: Whether to run browser in headless mode (default: False)
        """
        model_name = model or os.getenv('MODEL_NAME', 'anthropic/claude-sonnet-4')
        self.llm = ChatOpenAI(
            model=model_name,
            base_url='https://openrouter.ai/api/v1',
            api_key=os.getenv('OPENROUTER_API_KEY'),
        )
        self.browser = browser
        self.session_manager = SessionManager()
        self.db = db
        self.headless = headless
    
    def _get_linkedin_about_url(self, company_url: str) -> str:
        """
        Construct LinkedIn about page URL from company URL
        
        Args:
            company_url: LinkedIn company page URL (e.g., https://www.linkedin.com/company/example/life)
        
        Returns:
            LinkedIn about page URL (e.g., https://www.linkedin.com/company/example/about)
        """
        # Remove trailing slash and any path after /company/
        url = company_url.rstrip('/')
        
        # Extract company slug from URL
        if '/company/' in url:
            parts = url.split('/company/')
            if len(parts) > 1:
                company_slug = parts[1].split('/')[0]
                return f"https://www.linkedin.com/company/{company_slug}/about"
        
        # Fallback: try to replace last part with /about
        if url.endswith('/life'):
            return url.replace('/life', '/about')
        
        # If no pattern matches, append /about
        return f"{url}/about"
    
    async def _summarize_page(self, url: str, page_type: str, browser: Optional[Browser] = None) -> Optional[str]:
        """
        Use browser-use to visit a page and create a summary
        
        Args:
            url: URL to visit
            page_type: Type of page (e.g., "LinkedIn company page", "LinkedIn about page", "company website")
            browser: Optional Browser instance (will create new one if not provided)
        
        Returns:
            Summary string or None if failed
        """
        try:
            # Create a fresh browser instance for this agent call to avoid session reset issues
            # All browsers use the same user_data_dir so cookies are shared
            if not browser:
                browser = self.session_manager.get_browser(headless=self.headless)
            
            task_prompt = f"""
            Visit the following URL: {url}
            
            Read and analyze the content on this {page_type}.
            
            After reading the page, create a comprehensive summary (2-3 paragraphs) that includes:
            - Key information about the company
            - Main products/services
            - Company values, mission, or culture (if available)
            - Notable details or highlights
            
            Once you have read and analyzed the page, use the 'done' action to return your summary.
            Provide the summary as text in the done action - write it clearly and comprehensively.
            """
            
            agent = Agent(
                task=task_prompt,
                llm=self.llm,
                browser=browser,
                use_vision=False,
                # Don't use output_model_schema - it conflicts with browser actions
            )
            
            logger.info(f"Summarizing {page_type} at {url}...")
            history = await agent.run(max_steps=15)
            
            # Extract summary from final_result() - this is where browser-use puts the done action text
            if hasattr(history, 'final_result'):
                final_result = history.final_result()
                if final_result:
                    logger.info(f"Extracting summary from final_result for {page_type}")
                    # Clean up the summary (remove any markdown formatting if present)
                    summary = str(final_result).strip()
                    if summary and len(summary) > 50:  # Ensure it's a real summary
                        logger.info(f"Successfully extracted summary from final_result for {page_type}")
                        return summary
            
            # Fallback: try messages
            if hasattr(history, 'messages') and history.messages:
                # Get the last message which should contain the summary
                last_message = history.messages[-1]
                if hasattr(last_message, 'content'):
                    summary = last_message.content
                elif isinstance(last_message, dict) and 'content' in last_message:
                    summary = last_message['content']
                else:
                    summary = str(last_message)
                
                summary = summary.strip()
                if summary and len(summary) > 50:
                    logger.info(f"Successfully extracted summary from messages for {page_type}")
                    return summary
            
            logger.warning(f"Could not extract summary from agent response for {page_type}")
            logger.debug(f"History type: {type(history)}, has structured_output: {hasattr(history, 'structured_output')}")
            return None
            
        except Exception as e:
            logger.error(f"Error summarizing {page_type} at {url}: {e}", exc_info=True)
            return None
    
    async def _extract_website_url(self, linkedin_url: str, browser: Optional[Browser] = None) -> Optional[str]:
        """
        Extract company website URL from LinkedIn page
        
        Args:
            linkedin_url: LinkedIn company page URL
            browser: Optional Browser instance (will create new one if not provided)
        
        Returns:
            Company website URL or None if not found
        """
        try:
            # Create a fresh browser instance for this agent call to avoid session reset issues
            # All browsers use the same user_data_dir so cookies are shared
            if not browser:
                browser = self.session_manager.get_browser(headless=self.headless)
            
            task_prompt = f"""
            Visit the following LinkedIn company page: {linkedin_url}
            
            Find and extract the company's website URL. Look for:
            - A "Website" link or button
            - Links in the company description
            - Contact information section
            
            Once you find the website URL, use the 'done' action to return ONLY the website URL.
            Format: Return just the URL (e.g., https://example.com) or "NOT_FOUND" if you cannot find it.
            Do not include any other text, just the URL or "NOT_FOUND".
            """
            
            agent = Agent(
                task=task_prompt,
                llm=self.llm,
                browser=browser,
                use_vision=False,
                # Don't use output_model_schema - it conflicts with browser actions
            )
            
            logger.info(f"Extracting website URL from LinkedIn page: {linkedin_url}...")
            history = await agent.run(max_steps=10)
            
            # Extract URL from final_result() - this is where browser-use puts the done action text
            if hasattr(history, 'final_result'):
                final_result = history.final_result()
                if final_result:
                    response = str(final_result).strip()
                    if response and response.upper() != "NOT_FOUND":
                        # Look for http:// or https:// URLs in the response
                        url_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+', response)
                        if url_match:
                            website_url = url_match.group(0).rstrip('.,;:!?)')
                            logger.info(f"Extracted website URL from final_result: {website_url}")
                            return website_url
                        elif response.startswith('http'):
                            logger.info(f"Using final_result as website URL: {response}")
                            return response
            
            # Fallback: try messages
            if hasattr(history, 'messages') and history.messages:
                last_message = history.messages[-1]
                if hasattr(last_message, 'content'):
                    response = last_message.content
                elif isinstance(last_message, dict) and 'content' in last_message:
                    response = last_message['content']
                else:
                    response = str(last_message)
                
                response = response.strip()
                if response and response.upper() != "NOT_FOUND":
                    url_match = re.search(r'https?://[^\s<>"{}|\\^`\[\]]+', response)
                    if url_match:
                        website_url = url_match.group(0).rstrip('.,;:!?)')
                        logger.info(f"Extracted website URL from messages: {website_url}")
                        return website_url
                    elif response.startswith('http'):
                        logger.info(f"Using message as website URL: {response}")
                        return response
            
            logger.warning("Could not extract website URL from LinkedIn page")
            return None
            
        except Exception as e:
            logger.error(f"Error extracting website URL from LinkedIn page: {e}", exc_info=True)
            return None
    
    async def research_company(self, job: JobListing) -> CompanyResearch:
        """
        Research a company for a given job using LinkedIn pages and company website
        
        Args:
            job: JobListing object with company information (must have company_url)
        
        Returns:
            CompanyResearch object with summaries and website URL
        """
        company_name = job.company
        company_url = str(job.company_url) if job.company_url else None
        
        if not company_url:
            logger.warning(f"No company_url found for job {job.job_id}, cannot research company")
            return CompanyResearch(
                job_id=job.job_id or "",
                company_name=company_name,
                recent_news=[],
                tech_stack=[]
            )
        
        logger.info(f"Researching company: {company_name} using LinkedIn URL: {company_url}")
        
        try:
            # Initialize research object
            research = CompanyResearch(
                job_id=job.job_id or "",
                company_name=company_name,
                linkedin_url=company_url,
                recent_news=[],
                tech_stack=[]
            )
            
            # Step 1: Summarize LinkedIn company page
            # Pass None to let _summarize_page create a fresh browser instance
            logger.info("Step 1: Summarizing LinkedIn company page...")
            linkedin_summary = await self._summarize_page(
                company_url,
                "LinkedIn company page",
                None
            )
            if linkedin_summary:
                research.linkedin_page_summary = linkedin_summary
                logger.info(f"✓ Successfully saved LinkedIn page summary ({len(linkedin_summary)} chars)")
            else:
                logger.warning("✗ Failed to extract LinkedIn page summary")
            
            # Step 2: Get LinkedIn about page URL and summarize it
            about_url = self._get_linkedin_about_url(company_url)
            logger.info(f"Step 2: Summarizing LinkedIn about page at {about_url}...")
            about_summary = await self._summarize_page(
                about_url,
                "LinkedIn about page",
                None
            )
            if about_summary:
                research.linkedin_about_summary = about_summary
                logger.info(f"✓ Successfully saved LinkedIn about summary ({len(about_summary)} chars)")
            else:
                logger.warning("✗ Failed to extract LinkedIn about summary")
            
            # Step 3: Extract company website URL from LinkedIn pages
            logger.info("Step 3: Extracting company website URL...")
            website_url = await self._extract_website_url(company_url, None)
            if website_url:
                research.website = website_url
                logger.info(f"✓ Successfully extracted website URL: {website_url}")
                
                # Step 4: Summarize company website
                logger.info(f"Step 4: Summarizing company website at {website_url}...")
                website_summary = await self._summarize_page(
                    website_url,
                    "company website",
                    None
                )
                if website_summary:
                    research.website_summary = website_summary
                    logger.info(f"✓ Successfully saved website summary ({len(website_summary)} chars)")
                else:
                    logger.warning("✗ Failed to extract website summary")
            else:
                logger.warning("✗ Could not extract company website URL, skipping website summary")
            
            # Save to database if db instance is available
            if self.db:
                try:
                    await self.db.save_company_research(job.job_id or "", research)
                    logger.info(f"Saved company research to database for job {job.job_id}")
                except Exception as e:
                    logger.error(f"Error saving research to database: {e}")
            
            logger.info(f"Completed research for {company_name}")
            return research
            
        except Exception as e:
            logger.error(f"Error researching company {company_name}: {e}", exc_info=True)
            # Return minimal research object on error
            return CompanyResearch(
                job_id=job.job_id or "",
                company_name=company_name,
                linkedin_url=company_url,
                recent_news=[],
                tech_stack=[]
            )
