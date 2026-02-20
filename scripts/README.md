# Pipeline Daemon System

This directory contains the decoupled pipeline system for automated LinkedIn job processing.

## Overview

The pipeline consists of three stages that run independently:

1. **Scrape Jobs** (`scrape_jobs.py`) - Scrapes N jobs per day from LinkedIn
2. **Enrich Companies** (`enrich_companies.py`) - Enriches company data for scraped jobs
3. **Generate Drafts** (`generate_drafts.py`) - Generates cold email drafts for enriched jobs

All stages communicate via MongoDB and track their state/retries independently.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Make sure your `.env` file has:
- `MONGODB_URI` - MongoDB connection string
- `JOB_KEYWORDS` - Default job search keywords (e.g., "software engineer")
- `JOB_LOCATION` - Default location filter (optional)
- `OPENROUTER_API_KEY` - API key for LLM calls

### 3. Configure Pipeline

Edit `pipeline_config.yaml` to customize:
- Scraper schedule (default: daily at 9 AM)
- Enricher schedule (default: every hour at :00)
- Generator schedule (default: every hour at :30)
- Batch sizes and retry limits

### 4. Start the Daemon

```bash
./scripts/start_pipeline.sh
```

### 5. Check Status

```bash
./scripts/status_pipeline.sh
```

### 6. Stop the Daemon

```bash
./scripts/stop_pipeline.sh
```

## How It Works

### Pipeline Flow

```
┌─────────────────┐
│  Daemon Starts  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  APScheduler    │
│  • Scrape: 9 AM │
│  • Enrich: :00  │
│  • Generate: :30│
└────────┬────────┘
         │
         ▼
    [Database]
         │
    ┌────┴────┐
    │         │
    ▼         ▼
[Scraped] [Enriched]
    │         │
    └────┬────┘
         ▼
  [Draft Generated]
```

### State Management

Jobs progress through these states:
- `pending` → Initial state
- `scraped` → After scraping
- `enriching` → Currently being enriched
- `enriched` → After enrichment
- `generating` → Currently generating draft
- `draft_generated` → After draft generation
- `failed` → After max retries exceeded

### Retry Logic

Each stage has configurable retry logic:
- **Max retries**: Default 3 attempts per stage
- **Retry tracking**: Stored in database per job
- **Failure handling**: Jobs marked as `failed` after max retries

## Manual Execution

You can also run stages manually for testing:

```bash
# Scrape jobs manually
python scripts/scrape_jobs.py --max-jobs 10 --keywords "python developer"

# Enrich companies manually
python scripts/enrich_companies.py --batch-size 5 --max-retries 3

# Generate drafts manually
python scripts/generate_drafts.py --batch-size 5 --max-retries 3
```

## Sleep Behavior

- **When Mac sleeps**: The daemon process pauses (no CPU usage)
- **When Mac wakes**: The daemon resumes automatically
- **If daemon stopped**: No tasks run until you start it again
- **On restart**: Processes any pending jobs from the database

## Monitoring

### View Logs

```bash
tail -f logs/pipeline.log
```

### Check Database

Use MongoDB tools or the existing CLI:

```bash
python main.py --list --status scraped
python main.py --list --status enriched
python main.py --list --status draft_generated
python main.py --list --status failed
```

## Configuration

Edit `pipeline_config.yaml`:

```yaml
scraper:
  schedule:
    hour: 9      # Daily at 9 AM
    minute: 0
  max_jobs_per_day: 50
  enabled: true

enricher:
  schedule:
    minute: 0    # Every hour at :00
  max_retries: 3
  batch_size: 10
  enabled: true

generator:
  schedule:
    minute: 30   # Every hour at :30
  max_retries: 3
  batch_size: 10
  enabled: true
```

## Troubleshooting

### Daemon won't start
- Check if already running: `./scripts/status_pipeline.sh`
- Check logs: `tail -f logs/pipeline.log`
- Remove stale PID file: `rm .pipeline.pid`

### Jobs stuck in a stage
- Check retry counts in database
- Manually run the stage script
- Check for errors in logs

### Daemon stops unexpectedly
- Check system logs
- Verify MongoDB connection
- Check disk space for logs

## Architecture Benefits

- ✅ **Decoupled**: Each stage runs independently
- ✅ **Resilient**: Retry logic per stage
- ✅ **Observable**: Full state tracking in database
- ✅ **Simple**: No external dependencies (no Celery/RQ)
- ✅ **Local-friendly**: Works on MacBook with sleep/wake
- ✅ **Easy control**: Simple start/stop scripts
