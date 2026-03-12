"""Template-based draft generator for LinkedIn notes (400 char limit). No AI."""

from pathlib import Path
from typing import Optional

from src.models import JobListing, CompanyResearch, GeneratedMessage
from src.utils.logger import logger


class TemplateDraftGenerator:
    """Generate LinkedIn note drafts from a fixed template. No LLM calls."""

    LINKEDIN_NOTE_MAX_CHARS = 400

    def __init__(self, template_path: Optional[str] = None):
        """Initialize with template path. Defaults to golden_drafts/linkedin_note_template.md"""
        if template_path:
            self.template_path = Path(template_path)
        else:
            project_root = Path(__file__).parent.parent
            self.template_path = project_root / "golden_drafts" / "linkedin_note_template.md"
        self._template: Optional[str] = None

    def _load_template(self) -> str:
        """Load template content. Raises FileNotFoundError if missing."""
        if self._template is not None:
            return self._template
        if not self.template_path.exists():
            raise FileNotFoundError(f"Template not found at {self.template_path}")
        with open(self.template_path, "r", encoding="utf-8") as f:
            self._template = f.read().strip()
        logger.info(f"Loaded LinkedIn note template from {self.template_path}")
        return self._template

    def build_message(self, job: JobListing, research: CompanyResearch) -> str:
        """Replace placeholders with job/research data. [Name] stays for manual fill-in."""
        template = self._load_template()
        return (
            template.replace("[CompanyName]", research.company_name)
            .replace("[JobRole]", job.title)
        )
        # [Name] intentionally left as [Name] - user fills during application

    async def generate_draft(
        self, job: JobListing, research: CompanyResearch
    ) -> Optional[GeneratedMessage]:
        """
        Generate a draft from the template. Same signature as DraftGenerator.generate_draft
        for drop-in replacement.
        """
        try:
            message_text = self.build_message(job, research)

            if len(message_text) > self.LINKEDIN_NOTE_MAX_CHARS:
                logger.warning(
                    f"Template message exceeds {self.LINKEDIN_NOTE_MAX_CHARS} chars "
                    f"({len(message_text)} chars). Consider shortening the template."
                )

            return GeneratedMessage(
                job_id=job.job_id or "",
                message_text=message_text,
                personalization_notes="Template-based (LinkedIn 400 char limit). [Name] filled manually.",
                status="pending",
            )
        except Exception as e:
            logger.error(f"Error building template draft for job {job.job_id}: {e}", exc_info=True)
            return None
