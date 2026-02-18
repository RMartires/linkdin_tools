"""Message generator using OpenRouter API"""

import os
from typing import Optional
from openai import OpenAI
from dotenv import load_dotenv

from src.models import GeneratedMessage, JobListing, CompanyResearch
from src.utils.logger import logger

load_dotenv()


class MessageGenerator:
    """Generate personalized messages using OpenRouter LLM"""
    
    def __init__(self, model: Optional[str] = None):
        """Initialize message generator with OpenRouter"""
        self.client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )
        self.model = model or os.getenv('MODEL_NAME')
    
    def _build_prompt(self, job: JobListing, research: Optional[CompanyResearch] = None) -> str:
        """Build prompt for message generation"""
        prompt = f"""Generate a professional, personalized LinkedIn connection request message for the following job opportunity:

Job Title: {job.title}
Company: {job.company}
Location: {job.location or 'Not specified'}
"""
        
        if job.description:
            prompt += f"\nJob Description Summary:\n{job.description[:500]}...\n"
        
        if job.skills:
            prompt += f"\nRequired Skills: {', '.join(job.skills)}\n"
        
        if research:
            prompt += f"\nCompany Information:\n"
            prompt += f"- Industry: {research.industry or 'Not specified'}\n"
            prompt += f"- Company Size: {research.size or 'Not specified'}\n"
            
            if research.recent_news:
                prompt += f"\nRecent Company News:\n"
                for news in research.recent_news[:3]:  # Top 3 news items
                    prompt += f"- {news}\n"
            
            if research.tech_stack:
                prompt += f"\nTechnology Stack: {', '.join(research.tech_stack)}\n"
            
            if research.culture_notes:
                prompt += f"\nCompany Culture Notes: {research.culture_notes}\n"
        
        prompt += """
Instructions:
- Write a professional, personalized connection request message (200-300 words)
- Show genuine interest in the company and role
- Reference specific details from the job description or company research
- Be concise but warm and engaging
- Avoid generic phrases
- Include why you're interested in this specific opportunity
- End with a call to action (e.g., asking for a conversation or expressing interest in learning more)

Generate only the message text, no additional formatting or explanations.
"""
        
        return prompt
    
    async def generate_message(
        self,
        job: JobListing,
        research: Optional[CompanyResearch] = None
    ) -> GeneratedMessage:
        """
        Generate a personalized message for a job
        
        Args:
            job: JobListing object
            research: Optional CompanyResearch object
        
        Returns:
            GeneratedMessage object
        """
        logger.info(f"Generating message for job: {job.title} at {job.company}")
        
        try:
            prompt = self._build_prompt(job, research)
            
            # Call OpenRouter API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional career advisor helping craft personalized LinkedIn connection requests. Write messages that are authentic, specific, and engaging."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.7,
                max_tokens=500
            )
            
            message_text = response.choices[0].message.content.strip()
            
            # Build personalization notes
            personalization_notes = []
            if research:
                if research.recent_news:
                    personalization_notes.append(f"Referenced recent company news")
                if research.tech_stack:
                    personalization_notes.append(f"Referenced tech stack: {', '.join(research.tech_stack[:3])}")
                if research.culture_notes:
                    personalization_notes.append("Referenced company culture")
            
            if job.skills:
                personalization_notes.append(f"Referenced required skills")
            
            notes_text = "; ".join(personalization_notes) if personalization_notes else "Standard message"
            
            message = GeneratedMessage(
                job_id=job.job_id or "",
                message_text=message_text,
                personalization_notes=notes_text,
                status="pending"
            )
            
            logger.info(f"Successfully generated message for {job.company}")
            return message
            
        except Exception as e:
            logger.error(f"Error generating message: {e}")
            # Return a basic message on error
            return GeneratedMessage(
                job_id=job.job_id or "",
                message_text=f"Hello! I'm interested in the {job.title} position at {job.company}. I'd love to learn more about this opportunity.",
                personalization_notes="Error occurred during generation",
                status="pending"
            )
