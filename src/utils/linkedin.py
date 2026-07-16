"""Shared LinkedIn scraping constants and helpers."""

from typing import Optional
from urllib.parse import unquote

BAD_JOB_TITLE_CHIPS = frozenset({
    "remote",
    "hybrid",
    "on-site",
    "onsite",
    "full-time",
    "part-time",
    "contract",
    "apply",
    "save",
})

PROTECTED_JOB_STATUSES = frozenset({
    "enriching",
    "enriched",
    "generating",
    "draft_generated",
    "message_generated",
})

COMPANY_SLUG_OVERRIDES = {
    "hiredddd": "Hired",
    "hirefeedd": "Hire Feed",
}


def is_bad_job_title(title: str) -> bool:
    return (title or "").strip().lower() in BAD_JOB_TITLE_CHIPS


def company_name_from_slug(slug: str) -> str:
    key = (slug or "").strip("/").lower()
    return COMPANY_SLUG_OVERRIDES.get(key, slug.replace("-", " ").title())


def company_name_from_url(company_url: Optional[str]) -> Optional[str]:
    if not company_url or "/company/" not in str(company_url):
        return None
    slug = str(company_url).split("/company/")[1].split("/")[0]
    return company_name_from_slug(slug)


def resolve_company_name(name: Optional[str], company_url: Optional[str]) -> str:
    """Prefer scraped name; fall back to slug from company URL."""
    cleaned = (name or "").strip()
    if cleaned and cleaned.lower() != "unknown":
        return cleaned
    return company_name_from_url(company_url) or "Unknown"


def sanitize_http_url(raw: Optional[str]) -> Optional[str]:
    """Normalize scraped website hrefs; return None if unusable."""
    if not raw:
        return None
    url = unquote(str(raw)).strip().rstrip(".,;:!?)")
    url = url.replace(" ", "")
    if not url.startswith(("http://", "https://")):
        return None
    host = url.split("://", 1)[-1].split("/", 1)[0]
    if "%" in host or "." not in host or " " in host:
        return None
    return url
