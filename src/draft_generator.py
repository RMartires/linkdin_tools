"""Draft generator for cold LinkedIn DMs to startup founders"""

import os
from pathlib import Path
from typing import Optional, List, Dict, Any
from openai import OpenAI
from dotenv import load_dotenv

from src.models import JobListing, CompanyResearch, GeneratedMessage
from src.database import Database
from src.utils.logger import logger

load_dotenv()


class DraftGenerator:
    """Generate cold LinkedIn DM drafts for job applications"""
    
    def __init__(self, model: Optional[str] = None, db: Optional[Database] = None, resume_path: Optional[str] = None):
        """Initialize draft generator
        
        Args:
            model: Optional model name override
            db: Optional Database instance
            resume_path: Optional path to resume PDF (defaults to 'resume.pdf' in project root)
        """
        model_name = model or os.getenv('MODEL_NAME', 'anthropic/claude-sonnet-4')
        self.client = OpenAI(
            base_url='https://openrouter.ai/api/v1',
            api_key=os.getenv('OPENROUTER_API_KEY'),
        )
        self.model = model_name
        self.db = db
        
        # Set resume path
        if resume_path:
            self.resume_path = Path(resume_path)
        else:
            project_root = Path(__file__).parent.parent
            self.resume_path = project_root / 'resumes/rohit_martires_resume_.pdf'
        
        # Load golden drafts
        project_root = Path(__file__).parent.parent
        self.golden_drafts_dir = project_root / 'golden_drafts'
        self._load_golden_drafts()
    
    def _load_golden_drafts(self):
        """Load golden draft templates and examples"""
        try:
            # Load cold email soul (system message)
            soul_path = self.golden_drafts_dir / 'cold_email_soul.md'
            if soul_path.exists():
                with open(soul_path, 'r', encoding='utf-8') as f:
                    self.cold_email_soul = f.read().strip()
                logger.info("Loaded cold_email_soul.md")
            else:
                logger.warning(f"cold_email_soul.md not found at {soul_path}")
                self.cold_email_soul = None
            
            # Load examples
            self.examples = []
            example_files = ['example_1.md', 'example_2.md']
            for example_file in example_files:
                example_path = self.golden_drafts_dir / example_file
                if example_path.exists():
                    with open(example_path, 'r', encoding='utf-8') as f:
                        self.examples.append(f.read().strip())
                    logger.info(f"Loaded {example_file}")
                else:
                    logger.warning(f"{example_file} not found at {example_path}")
        except Exception as e:
            logger.error(f"Error loading golden drafts: {e}")
            self.cold_email_soul = None
            self.examples = []
    
    def _read_resume_pdf(self) -> Optional[str]:
        """Read resume PDF and extract text
        
        Returns:
            Resume text or None if file not found
        """
        if not self.resume_path.exists():
            logger.warning(f"Resume file not found at: {self.resume_path}")
            return None
        
        try:
            # Try using PyPDF2 first
            try:
                import PyPDF2
                with open(self.resume_path, 'rb') as file:
                    pdf_reader = PyPDF2.PdfReader(file)
                    text = ""
                    for page in pdf_reader.pages:
                        text += page.extract_text() + "\n"
                    logger.info(f"Successfully read resume PDF ({len(text)} chars)")
                    return text.strip()
            except ImportError:
                logger.debug("PyPDF2 not available, trying pdfplumber")
            
            # Fallback to pdfplumber
            try:
                import pdfplumber
                with pdfplumber.open(self.resume_path) as pdf:
                    text = ""
                    for page in pdf.pages:
                        text += page.extract_text() + "\n"
                    logger.info(f"Successfully read resume PDF using pdfplumber ({len(text)} chars)")
                    return text.strip()
            except ImportError:
                logger.error("Neither PyPDF2 nor pdfplumber is installed. Install one with: pip install PyPDF2 or pip install pdfplumber")
                return None
                
        except Exception as e:
            logger.error(f"Error reading resume PDF: {e}")
            return None
    
    def _build_messages(self, job: JobListing, research: CompanyResearch, resume_text: str) -> List[dict]:
        """Build structured messages for OpenAI API with system message, user message, and examples
        
        Args:
            job: JobListing object
            research: CompanyResearch object
            resume_text: Resume text content
        
        Returns:
            List of message dictionaries for OpenAI API
        """
        messages = []
        
        # System message: Use cold_email_soul.md
        if self.cold_email_soul:
            # Replace placeholders with actual values
            system_content = (
                self.cold_email_soul.replace("[Company Name]", research.company_name)
                .replace("[Founder Name]", "the founder")
            )
            messages.append({
                "role": "system",
                "content": system_content
            })
        else:
            # Fallback if soul file not found
            messages.append({
                "role": "system",
                "content": "You are an elite software engineer. Write a compelling cold LinkedIn DM to a startup founder."
            })
        
        # Collect company metadata (from Playwright researcher)
        meta_parts = []
        if research.industry:
            meta_parts.append(f"Industry: {research.industry}")
        if research.size:
            meta_parts.append(f"Company size: {research.size}")
        if research.website:
            meta_parts.append(f"Website: {research.website}")
        if research.linkedin_url:
            meta_parts.append(f"LinkedIn: {research.linkedin_url}")
        company_meta = "\n".join(meta_parts) if meta_parts else ""

        # Collect available summaries
        summaries = []
        if company_meta:
            summaries.append(company_meta + "\n")
        if research.linkedin_page_summary:
            summaries.append(f"LinkedIn Company Page Summary:\n{research.linkedin_page_summary}\n")
        if research.linkedin_about_summary:
            summaries.append(f"LinkedIn About Page Summary:\n{research.linkedin_about_summary}\n")
        if research.website_summary:
            summaries.append(f"Company Website Summary:\n{research.website_summary}\n")

        company_info = "\n".join(summaries)
        
        # Build job details
        job_details = f"""Job Title: {job.title}
Company: {job.company}
Location: {job.location or 'Not specified'}
Job URL: {job.url}"""
        
        if job.description:
            job_details += f"\n\nJob Description:\n{job.description}"

        # Target Mission: company mission/values for personalizing the opening
        target_mission = (
            research.linkedin_about_summary
            or research.linkedin_page_summary
            or research.website_summary
            or ""
        )[:600]

        # Specific Technical Win: resume excerpt for model to extract relevant achievement
        specific_technical_win = (resume_text[:800] + "...") if resume_text and len(resume_text) > 800 else (resume_text or "")
                
        # User message: LinkedIn DM context
        user_content = f"""Write a short cold LinkedIn DM for the founder at {research.company_name} for this role:

JOB DETAILS:
{job_details}

TARGET MISSION (use this to personalize the opening):
{target_mission or company_info}

SPECIFIC TECHNICAL WIN (draw from resume to establish credibility):
{specific_technical_win}

COMPANY RESEARCH (full context):
{company_info}

MY RESUME:
{resume_text}

Output ONLY the LinkedIn DM message body (60-75 words). No subject line, no greeting line—start with "I love everything about what [Company Name] is doing". Ready to paste into LinkedIn."""
        
        # Add examples if available
        if self.examples:
            user_content += "\n\nEXAMPLES OF SIMILAR LINKEDIN DMs:\n\n"
            for i, example in enumerate(self.examples, 1):
                user_content += f"Example {i}:\n{example}\n\n"
        
        messages.append({
            "role": "user",
            "content": user_content
        })
        
        return messages

    def _build_messages_for_person(
        self,
        person: Dict[str, Any],
        job: JobListing,
        research: CompanyResearch,
        resume_text: str,
    ) -> List[dict]:
        """Build messages for per-person draft with the custom template format."""
        full_name = person.get("name") or ""
        person_name = full_name.split()[0] if full_name.strip() else "there"
        specific_technical_win = (
            (resume_text[:800] + "...") if resume_text and len(resume_text) > 800 else (resume_text or "")
        )

        user_content = f"""Write a short cold LinkedIn DM for {person_name} at {research.company_name}.

Use this EXACT structure (fill in the bracketed parts):

Hey {person_name},
I love everything about what {research.company_name} is doing, would love to give an interview

[Write 1-2 sentences here: extract your most relevant technical achievement from the resume below - e.g. "I've scaled internal services to thousands of workflows and users, launching a Shopify app to 10k MAUs and handling 100M+ events/day."]

I applied to the {job.title} role, could you refer me?

RESUME (extract technical win from here):
{resume_text}

Output ONLY the LinkedIn DM message body. No extra text. Use the exact greeting "Hey {person_name}," and exact closing "I applied to the {job.title} role, could you refer me?" Fill the middle with 1-2 sentences from the resume."""
        return [
            {"role": "system", "content": "You are an elite software engineer. Write a concise, high-signal LinkedIn DM. Extract specific technical achievements from the resume."},
            {"role": "user", "content": user_content},
        ]

    def _generate_draft_for_person(
        self,
        person: Dict[str, Any],
        job: JobListing,
        research: CompanyResearch,
        resume_text: str,
    ) -> Optional[str]:
        """Generate a single draft message for one key contact. Returns message text or None."""
        try:
            messages = self._build_messages_for_person(person, job, research, resume_text)
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.5,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"Failed to generate draft for {person.get('name', 'unknown')}: {e}")
            return None

    async def generate_draft(self, job: JobListing, research: CompanyResearch) -> Optional[GeneratedMessage]:
        """Generate a cold LinkedIn DM draft for a job
        
        Args:
            job: JobListing object
            research: CompanyResearch object
        
        Returns:
            GeneratedMessage object or None if generation fails
        """
        # Validate that research has at least one summary
        if not any([research.linkedin_page_summary, research.linkedin_about_summary, research.website_summary]):
            logger.warning(f"No summaries available for job {job.job_id}. Need at least one of: linkedin_page_summary, linkedin_about_summary, or website_summary")
            return None
        
        # Read resume
        resume_text = self._read_resume_pdf()
        if not resume_text:
            logger.error("Could not read resume PDF. Cannot generate draft without resume.")
            return None

        # If key_contacts exist, generate one draft per person
        if research.key_contacts and len(research.key_contacts) > 0:
            personalized_drafts: List[Dict[str, Any]] = []
            for person in research.key_contacts:
                msg_text = self._generate_draft_for_person(person, job, research, resume_text)
                if msg_text:
                    personalized_drafts.append({
                        "name": person.get("name"),
                        "profile_url": person.get("profile_url"),
                        "message_text": msg_text,
                    })
                    logger.info(f"Generated draft for {person.get('name', 'unknown')}")

            if not personalized_drafts:
                logger.warning("No personalized drafts generated from key_contacts, falling back to generic")
                # Fall through to generic draft
            else:
                # Combine messages with \n\n for display; first draft as message_text for backward compat
                combined_message = "\n\n".join(d["message_text"] for d in personalized_drafts)
                return GeneratedMessage(
                    job_id=job.job_id or "",
                    message_text=personalized_drafts[0]["message_text"],
                    personalization_notes=f"Generated {len(personalized_drafts)} personalized drafts for key contacts.",
                    personalized_drafts=personalized_drafts,
                    status="pending",
                )

        # Generic draft (no key_contacts or fallback)
        messages = self._build_messages(job, research, resume_text)

        try:
            logger.info(f"Generating cold LinkedIn DM for job: {job.title} at {job.company}")

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
            )

            raw_content = response.choices[0].message.content
            message_text = raw_content.strip()

            if "Subject:" in message_text and "\n\n" in message_text:
                parts = message_text.split("\n\n", 1)
                if len(parts) == 2 and "Subject:" in parts[0]:
                    message_text = parts[1].strip()

            return GeneratedMessage(
                job_id=job.job_id or "",
                message_text=message_text,
                personalization_notes="Generated cold LinkedIn DM using company research and resume.",
                status="pending",
            )

        except Exception as e:
            logger.error(f"Error generating draft for job {job.job_id}: {e}", exc_info=True)
            return None
    
    async def generate_drafts_for_jobs(
        self,
        job_ids: Optional[List[str]] = None,
        filters: Optional[dict] = None
    ) -> List[GeneratedMessage]:
        """Generate drafts for multiple jobs
        
        Args:
            job_ids: Optional list of specific job IDs to process
            filters: Optional filters for querying jobs
        
        Returns:
            List of GeneratedMessage objects
        """
        if not self.db:
            logger.error("Database instance not provided. Cannot fetch jobs.")
            return []
        
        # Get jobs
        if job_ids:
            jobs = []
            for job_id in job_ids:
                job = await self.db.get_job_by_id(job_id)
                if job:
                    jobs.append(job)
        else:
            filters = filters or {}
            jobs = await self.db.get_jobs(filters=filters, limit=100)
        
        if not jobs:
            logger.warning("No jobs found to generate drafts for")
            return []
        
        logger.info(f"Generating drafts for {len(jobs)} jobs...")
        
        generated_drafts = []
        for job in jobs:
            # Get company research by company name
            research = await self.db.get_company_research_by_name(job.company)
            
            if not research:
                logger.warning(f"No company research found for company {job.company} (job {job.job_id}). Skipping.")
                continue
            
            # Validate research has summaries
            if not any([research.linkedin_page_summary, research.linkedin_about_summary, research.website_summary]):
                logger.warning(f"Job {job.job_id} has research but no summaries. Skipping.")
                continue
            
            # Generate draft
            draft = await self.generate_draft(job, research)
            if draft:
                generated_drafts.append(draft)
                
                # Save to database
                try:
                    await self.db.save_message(job.job_id, draft)
                    logger.info(f"Saved draft to database for job {job.job_id}")
                except Exception as e:
                    logger.error(f"Error saving draft to database: {e}")
        
        logger.info(f"Generated {len(generated_drafts)} drafts")
        return generated_drafts
