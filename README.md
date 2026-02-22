# LinkedIn Job Automation Tool

Automated tool for scraping LinkedIn jobs, researching companies, and generating personalized messages using browser-use and OpenRouter LLM.

## Features

- **Job Scraping**: Automatically scrape LinkedIn job listings using browser-use
- **Company Research**: Research each company using browser automation
- **Message Generation**: Generate personalized messages using OpenRouter LLM API
- **MongoDB Storage**: All data stored in MongoDB for easy querying and management
- **Export**: Export results to JSON or CSV for review

## Setup

1. **Install uv (if not already installed):**
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   # or on macOS with Homebrew
   brew install uv
   ```

2. **Create virtual environment and install dependencies:**
   
   **Option A: Using uv sync (recommended - uses pyproject.toml)**
   ```bash
   # This creates venv and installs all dependencies automatically
   uv sync
   
   # Activate the virtual environment
   source .venv/bin/activate  # On macOS/Linux
   # or
   .venv\Scripts\activate  # On Windows
   ```
   
   **Option B: Using uv pip (uses requirements.txt)**
   ```bash
   # Create virtual environment
   uv venv
   
   # Activate virtual environment
   source .venv/bin/activate  # On macOS/Linux
   # or
   .venv\Scripts\activate  # On Windows
   
   # Install dependencies
   uv pip install -r requirements.txt
   ```

3. **Install browser-use browser (Chromium):**
   ```bash
   uvx browser-use install
   ```

3. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

4. **Set up MongoDB:**
   - **Local MongoDB**: Install MongoDB locally and use `mongodb://localhost:27017/linkedin_automate`
   - **MongoDB Atlas**: Create a free cluster at https://www.mongodb.com/cloud/atlas and use the connection string
   - Update `MONGODB_URI` in `.env`

5. **Get API keys and configure:**
   - **OpenRouter API key**: Get one at https://openrouter.ai/keys
   - Add to `.env` as `OPENROUTER_API_KEY`
   - **Model selection**: Set `MODEL_NAME` in `.env`
     - Examples: `openai/gpt-4o`, `google/gemini-pro`, `anthropic/claude-sonnet-4`
     - See available models at https://openrouter.ai/models

6. **Export LinkedIn cookies (one-time setup, repeat when session expires):**
   ```bash
   # Log into LinkedIn in Chrome first, then run:
   python scripts/export_linkedin_cookies.py
   ```
   - **macOS**: Requires Full Disk Access for Terminal (System Settings → Privacy & Security)
   - Uses your Chrome profile from `BROWSER_PROFILE_DIRECTORY` in `.env` (default: Profile 3)
   - Creates `linkedin_storage_state.json` with your session
   - Re-run when LinkedIn logs you out (typically every few weeks)

## Usage

### Run Full Pipeline

Scrape jobs, research companies, and generate messages:

```bash
# Basic usage
python main.py --keywords "software engineer" --location "San Francisco"

# With filters
python main.py --keywords "python developer" --location "Remote" --experience-level "Mid" --max-results 20

# Skip research or message generation
python main.py --keywords "data scientist" --skip-research
python main.py --keywords "backend engineer" --skip-messages
```

### List Jobs

View jobs stored in the database:

```bash
# List all jobs
python main.py --list

# List pending jobs
python main.py --list --status pending --limit 50
```

### Export Data

Export jobs and messages to JSON or CSV:

```bash
# Export pending messages to CSV
python main.py --export csv --status pending --output messages.csv

# Export all jobs to JSON
python main.py --export json --output jobs.json

# Export with filters
python main.py --export csv --company "Google" --date-from 2025-02-01 --date-to 2025-02-18
```

### Command Line Options

- `--keywords`: Job search keywords (required for scraping)
- `--location`: Location filter
- `--experience-level`: Filter by experience (Entry, Mid, Senior)
- `--job-type`: Filter by job type
- `--max-results`: Maximum number of jobs to scrape (default: 50)
- `--skip-research`: Skip company research phase
- `--skip-messages`: Skip message generation phase
- `--export`: Export format (json or csv)
- `--output`: Output filename
- `--status`: Filter by status
- `--company`: Filter by company name
- `--date-from`: Filter from date (YYYY-MM-DD)
- `--date-to`: Filter to date (YYYY-MM-DD)
- `--list`: List jobs from database
- `--limit`: Limit for list command (default: 20)

## Troubleshooting

### LinkedIn storage state not found

If you see `LinkedIn storage state not found`, run the export script first:

```bash
python scripts/export_linkedin_cookies.py
```

### Full Disk Access required (macOS)

The cookie export needs to read Chrome's encrypted cookie database. Grant **Full Disk Access** to Terminal (or your IDE's terminal) in System Settings → Privacy & Security → Full Disk Access.

### LinkedIn session expired

If the scraper shows LinkedIn's login page, your cookies have expired. Re-export:

```bash
python scripts/export_linkedin_cookies.py
```

## Project Structure

```
linkdin-automate/
├── src/
│   ├── models.py              # Pydantic data models
│   ├── database.py            # MongoDB operations
│   ├── job_scraper.py         # LinkedIn job scraping
│   ├── company_researcher.py  # Company research
│   ├── message_generator.py   # Message generation
│   ├── orchestrator.py        # Workflow orchestration
│   └── utils/
│       ├── export.py          # Export utilities
│       └── logger.py          # Logging
└── main.py                    # CLI entry point
```

## License

MIT
