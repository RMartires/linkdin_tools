"""Google Sheets client for pipeline job tracking"""

import os
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

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

    Columns: Job ID | Job Title | Company | LinkedIn Company URL | Search Query | Draft Generated | Custom Message | Profile Link

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
            cols=8,
        )

        # Header row
        headers = [
            "Job ID", "Job Title", "Company", "LinkedIn Company URL", "Search Query",
            "Draft Generated", "Custom Message", "Profile Link",
        ]
        worksheet.update("A1:H1", [headers])

        # Data rows
        rows = []
        for job in jobs:
            company_url = str(job.company_url) if job.company_url else ""
            rows.append([
                job.job_id or "",
                job.title or "",
                job.company or "",
                company_url,
                search_query,
                "",  # Draft Generated - empty initially
                "",  # Custom Message - empty initially
                "",  # Profile Link - empty initially
            ])

        if rows:
            worksheet.update(f"A2:H{len(rows) + 1}", rows)

        logger.info(f"Created worksheet '{worksheet_title}' with {len(jobs)} jobs")
        return worksheet_title

    except Exception as e:
        logger.error(f"Failed to create worksheet and append jobs: {e}", exc_info=True)
        return None


def update_draft_in_latest_worksheet(
    spreadsheet_id: str,
    job_id: str,
    draft_value: str = "Yes",
    personalized_drafts: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Find job_id across all worksheets and update Draft Generated (F), Custom Message (G), Profile Link (H).

    For multiple persons (personalized_drafts): one row per person, each with that person's draft
    and profile link. Job info (A-E) is repeated on each row.

    Args:
        spreadsheet_id: Google Sheets spreadsheet ID
        job_id: Job ID to find
        draft_value: Value for Draft Generated column (F) - used when no personalized_drafts
        personalized_drafts: Optional list of {name, profile_url, message_text} for per-contact drafts

    Returns True if updated successfully, False otherwise.
    """
    try:
        gc = _get_client()
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheets = spreadsheet.worksheets()

        if not worksheets:
            logger.warning("No worksheets found in spreadsheet")
            return False

        for worksheet in reversed(worksheets):
            cells = worksheet.findall(job_id)
            if cells:
                cell = cells[0]
                row = cell.row

                # Read existing row to get job info (A-E)
                existing_row = worksheet.row_values(row)
                # Pad to 8 cols: Job ID, Job Title, Company, LinkedIn Company URL, Search Query, Draft, Custom, Profile
                job_info = (existing_row + [""] * 8)[:5]

                if personalized_drafts and len(personalized_drafts) > 0:
                    # One row per person: draft (F) + profile link (H) for each
                    rows_to_write = []
                    for d in personalized_drafts:
                        draft_text = d.get("message_text", "") or ""
                        profile_url = d.get("profile_url", "") or ""
                        rows_to_write.append(
                            job_info + [draft_text, "", profile_url]
                        )
                    # Update first row with person 1's data
                    worksheet.update(f"A{row}:H{row}", [rows_to_write[0]])
                    # Insert additional rows for persons 2..N below
                    if len(rows_to_write) > 1:
                        worksheet.insert_rows(rows_to_write[1:], row=row + 1)
                    logger.info(
                        f"Updated draft for job {job_id} in worksheet '{worksheet.title}' "
                        f"({len(rows_to_write)} rows, one per person)"
                    )
                else:
                    # Single row: legacy behavior
                    custom_message = draft_value
                    profile_link = ""
                    range_ref = f"F{row}:H{row}"
                    worksheet.update(range_ref, [[draft_value, custom_message, profile_link]])
                    logger.info(f"Updated draft for job {job_id} in worksheet '{worksheet.title}'")

                return True

        logger.warning(f"Could not find job_id '{job_id}' in any worksheet")
        return False

    except Exception as e:
        logger.error(f"Failed to update draft for job {job_id}: {e}", exc_info=True)
        return False
