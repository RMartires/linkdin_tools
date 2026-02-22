"""Google Sheets client for pipeline job tracking"""

import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.models import JobListing
from src.utils.logger import logger

# Lazy import gspread to avoid import errors when not configured
_gspread = None
_gc = None


def _get_client():
    """Get or create gspread client (lazy init)"""
    global _gc
    if _gc is not None:
        return _gc
    try:
        import gspread
        creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if creds_path and Path(creds_path).exists():
            _gc = gspread.service_account(filename=creds_path)
        else:
            _gc = gspread.service_account()
        return _gc
    except Exception as e:
        logger.error(f"Failed to initialize Google Sheets client: {e}")
        raise


def _generate_worksheet_title() -> str:
    """Generate worksheet title: YYYY-MM-DD_<random_suffix>"""
    date_str = datetime.now().strftime("%Y-%m-%d")
    suffix = secrets.token_hex(3)
    return f"{date_str}_{suffix}"


def create_worksheet_and_append_jobs(
    spreadsheet_id: str,
    jobs: List[JobListing],
    search_query: str = "",
    credentials_path: Optional[str] = None,
) -> Optional[str]:
    """
    Create a new worksheet with today's date + random suffix and append job rows.

    Columns: Job ID | Job Title | Company | LinkedIn Company URL | Search Query | Draft Generated

    Args:
        spreadsheet_id: Google Sheets spreadsheet ID
        jobs: List of job listings to append
        search_query: Search query string (title and location) to add to each row
        credentials_path: Optional path to credentials file

    Returns the worksheet title if successful, None otherwise.
    """
    try:
        gc = _get_client()
        spreadsheet = gc.open_by_key(spreadsheet_id)

        worksheet_title = _generate_worksheet_title()
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_title,
            rows=max(len(jobs) + 10, 100),
            cols=6,  # Updated to 6 columns
        )

        # Header row - now includes Search Query column
        headers = ["Job ID", "Job Title", "Company", "LinkedIn Company URL", "Search Query", "Draft Generated"]
        worksheet.update("A1:F1", [headers])

        # Data rows
        rows = []
        for job in jobs:
            company_url = str(job.company_url) if job.company_url else ""
            rows.append([
                job.job_id or "",
                job.title or "",
                job.company or "",
                company_url,
                search_query,  # Search Query column
                "",  # Draft Generated - empty initially
            ])

        if rows:
            worksheet.update(f"A2:F{len(rows) + 1}", rows)

        logger.info(f"Created worksheet '{worksheet_title}' with {len(jobs)} jobs")
        return worksheet_title

    except Exception as e:
        logger.error(f"Failed to create worksheet and append jobs: {e}", exc_info=True)
        return None


def update_draft_in_latest_worksheet(
    spreadsheet_id: str,
    job_id: str,
    draft_value: str = "Yes",
) -> bool:
    """
    Find job_id in the latest worksheet (by index) and update the Draft Generated column.

    Returns True if updated successfully, False otherwise.
    """
    try:
        gc = _get_client()
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheets = spreadsheet.worksheets()

        if not worksheets:
            logger.warning("No worksheets found in spreadsheet")
            return False

        # Latest worksheet = last in list (most recently added)
        latest = worksheets[-1]
        cells = latest.findall(job_id)
        if not cells:
            logger.warning(f"Could not find job_id '{job_id}' in latest worksheet '{latest.title}'")
            return False
        cell = cells[0]

        # Draft Generated is column F (6th column), same row (moved due to Search Query column)
        row = cell.row
        col_letter = "F"
        range_ref = f"{col_letter}{row}"
        latest.update(range_ref, [[draft_value]])
        logger.info(f"Updated draft status for job {job_id} in worksheet '{latest.title}'")
        return True

    except Exception as e:
        logger.error(f"Failed to update draft for job {job_id}: {e}", exc_info=True)
        return False
