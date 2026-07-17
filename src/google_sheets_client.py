"""Google Sheets client for pipeline job tracking.

Single "Jobs" worksheet layout (columns A-J):
    Job ID | Job Title | Company | Location | Job URL | Company URL |
    Search Query | Message | Status | Date Scraped
"""

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.models import JobListing
from src.utils.logger import logger

WORKSHEET_TITLE = "Jobs"
HEADERS = [
    "Job ID", "Job Title", "Company", "Location",
    "Job URL", "Company URL", "Search Query", "Message",
    "Status", "Date Scraped",
]
NUM_COLS = len(HEADERS)
MESSAGE_COL = 8   # column H (1-based)
STATUS_COL = 9    # column I
DATE_SCRAPED_COL = 10  # column J

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


def _format_date_scraped(job: JobListing) -> str:
    """Format scraped date for the sheet (YYYY-MM-DD)."""
    dt = job.scraped_at or job.created_at
    if not dt:
        return datetime.utcnow().strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d")


def _ensure_worksheet_headers(worksheet) -> None:
    """Keep header row in sync when columns are added."""
    existing = worksheet.row_values(1)
    if existing != HEADERS:
        worksheet.update("A1", [HEADERS])


def _get_jobs_worksheet(spreadsheet):
    """Get the single Jobs worksheet, creating it with headers if missing."""
    try:
        worksheet = spreadsheet.worksheet(WORKSHEET_TITLE)
        _ensure_worksheet_headers(worksheet)
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
        job.status or "scraped",
        _format_date_scraped(job),
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
    status: Optional[str] = None,
    date_scraped: Optional[str] = None,
) -> bool:
    """
    Write the generated message (and optional status) for a job row.

    For per-person drafts (personalized_drafts): one row per person, job info
    (A-G, I-J) repeated, each row carrying that person's message in column H.

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
            base = (existing_row + [""] * NUM_COLS)[:NUM_COLS]
            if status:
                base[STATUS_COL - 1] = status
            if date_scraped:
                base[DATE_SCRAPED_COL - 1] = date_scraped
            rows_to_write = []
            for d in personalized_drafts:
                row_data = list(base)
                row_data[MESSAGE_COL - 1] = d.get("message_text", "") or ""
                rows_to_write.append(row_data)
            worksheet.update(f"A{row}:J{row}", [rows_to_write[0]])
            if len(rows_to_write) > 1:
                worksheet.insert_rows(rows_to_write[1:], row=row + 1)
            logger.info(
                f"Sheets: wrote {len(rows_to_write)} per-person messages for job {job_id}"
            )
        else:
            worksheet.update_cell(row, MESSAGE_COL, message_text)
            if status:
                worksheet.update_cell(row, STATUS_COL, status)
            if date_scraped:
                worksheet.update_cell(row, DATE_SCRAPED_COL, date_scraped)
            logger.info(f"Sheets: wrote message for job {job_id}")

        return True

    except Exception as e:
        logger.error(f"Failed to update message for job {job_id}: {e}", exc_info=True)
        return False
