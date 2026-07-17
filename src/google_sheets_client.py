"""Google Sheets client for pipeline job tracking.

Single "Jobs" worksheet layout (columns A-H):
    Job ID | Job Title | Company | Location | Job URL | Company URL | Search Query | Message
"""

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import JobListing
from src.utils.logger import logger

WORKSHEET_TITLE = "Jobs"
HEADERS = [
    "Job ID", "Job Title", "Company", "Location",
    "Job URL", "Company URL", "Search Query", "Message",
]
NUM_COLS = len(HEADERS)
MESSAGE_COL = NUM_COLS  # column H

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


def _get_jobs_worksheet(spreadsheet):
    """Get the single Jobs worksheet, creating it with headers if missing."""
    try:
        worksheet = spreadsheet.worksheet(WORKSHEET_TITLE)
    except Exception:
        worksheet = spreadsheet.add_worksheet(title=WORKSHEET_TITLE, rows=1000, cols=NUM_COLS)
        worksheet.update("A1", [HEADERS])
        logger.info(f"Created '{WORKSHEET_TITLE}' worksheet")
    return worksheet


def _job_to_row(job: JobListing, search_query: str) -> List[str]:
    return [
        job.job_id or "",
        job.title or "",
        job.company or "",
        job.location or "",
        str(job.url) if job.url else "",
        str(job.company_url) if job.company_url else "",
        search_query,
        "",  # Message - filled after draft generation
    ]


def upsert_jobs(
    spreadsheet_id: str,
    jobs: List[JobListing],
    search_query: str = "",
) -> int:
    """
    Append jobs to the single Jobs worksheet, skipping job IDs already present.

    Returns the number of rows appended (0 on no-op, -1 on failure).
    """
    try:
        gc = _get_client()
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheet = _get_jobs_worksheet(spreadsheet)

        existing_ids = set(worksheet.col_values(1)[1:])  # skip header
        new_rows = [
            _job_to_row(job, search_query)
            for job in jobs
            if job.job_id and job.job_id not in existing_ids
        ]

        if new_rows:
            worksheet.append_rows(new_rows, value_input_option="RAW")

        skipped = len(jobs) - len(new_rows)
        logger.info(
            f"Sheets: appended {len(new_rows)} new jobs to '{WORKSHEET_TITLE}' "
            f"({skipped} already present)"
        )
        return len(new_rows)

    except Exception as e:
        logger.error(f"Failed to upsert jobs to Google Sheets: {e}", exc_info=True)
        return -1


def update_job_message(
    spreadsheet_id: str,
    job_id: str,
    message_text: str,
    personalized_drafts: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Write the generated message into the Message column for a job row.

    For per-person drafts (personalized_drafts): one row per person, job info
    (A-G) repeated, each row carrying that person's message.

    Returns True if updated successfully, False otherwise.
    """
    try:
        gc = _get_client()
        spreadsheet = gc.open_by_key(spreadsheet_id)
        worksheet = _get_jobs_worksheet(spreadsheet)

        id_column = worksheet.col_values(1)
        try:
            row = id_column.index(job_id) + 1  # 1-based row number
        except ValueError:
            logger.warning(f"Could not find job_id '{job_id}' in '{WORKSHEET_TITLE}' worksheet")
            return False

        if personalized_drafts:
            existing_row = worksheet.row_values(row)
            job_info = (existing_row + [""] * NUM_COLS)[: NUM_COLS - 1]
            rows_to_write = [
                job_info + [d.get("message_text", "") or ""]
                for d in personalized_drafts
            ]
            worksheet.update(f"A{row}:H{row}", [rows_to_write[0]])
            if len(rows_to_write) > 1:
                worksheet.insert_rows(rows_to_write[1:], row=row + 1)
            logger.info(
                f"Sheets: wrote {len(rows_to_write)} per-person messages for job {job_id}"
            )
        else:
            worksheet.update_cell(row, MESSAGE_COL, message_text)
            logger.info(f"Sheets: wrote message for job {job_id}")

        return True

    except Exception as e:
        logger.error(f"Failed to update message for job {job_id}: {e}", exc_info=True)
        return False
