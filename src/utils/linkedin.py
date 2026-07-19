"""Shared LinkedIn scraping constants and helpers."""

import json
from pathlib import Path
from typing import Optional, Set
from urllib.parse import unquote

from src.utils.logger import logger

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

# Project-root JSON file you can edit to skip companies during scrape
COMPANY_SKIPLIST_PATH = Path(__file__).resolve().parent.parent.parent / "company_skiplist.json"


def load_company_skiplist() -> Set[str]:
    """Load company names to skip (case-insensitive). Empty set if file missing/invalid."""
    path = COMPANY_SKIPLIST_PATH
    if not path.exists():
        logger.debug(f"Company skiplist not found at {path}")
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        companies = data.get("companies", data if isinstance(data, list) else [])
        names = {
            str(name).strip().lower()
            for name in companies
            if str(name).strip()
        }
        return names
    except Exception as e:
        logger.warning(f"Failed to load company skiplist from {path}: {e}")
        return set()


def is_company_skipped(company_name: Optional[str], company_url: Optional[str] = None) -> bool:
    """True if company name or URL slug is on the local skiplist."""
    skiplist = load_company_skiplist()
    if not skiplist:
        return False

    name = (company_name or "").strip().lower()
    if name and name in skiplist:
        return True

    # Also match names resolved from LinkedIn company URL slugs
    from_url = company_name_from_url(company_url)
    if from_url and from_url.strip().lower() in skiplist:
        return True

    return False


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
