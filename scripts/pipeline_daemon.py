"""Pipeline daemon with APScheduler for scheduled job processing"""

import asyncio
import os
import signal
import sys
import threading
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# Add parent directory to path for src imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.logger import logger

# Import stage functions from current directory
import scrape_jobs
import enrich_companies
import generate_drafts

scrape_jobs_stage = scrape_jobs.scrape_jobs_stage
enrich_companies_stage = enrich_companies.enrich_companies_stage
generate_drafts_stage = generate_drafts.generate_drafts_stage

load_dotenv()


def _run_async(coro):
    """Run async coroutine from sync context (used by BackgroundScheduler)"""
    asyncio.run(coro)


class PipelineDaemon:
    """Daemon that runs scheduled pipeline stages"""
    
    def __init__(self, config_path: str = None):
        """Initialize daemon with configuration"""
        self.config_path = config_path or Path(__file__).parent / "pipeline_config.yaml"
        self.config = self._load_config()
        self.scheduler = BackgroundScheduler(daemon=False)  # daemon=False so it keeps process alive
        self.running = True
        self._shutdown_event = threading.Event()
        self.pid_file = Path(__file__).parent.parent / self.config["daemon"]["pid_file"]
        self.log_file = Path(__file__).parent.parent / self.config["daemon"]["log_file"]
        
    def _load_config(self) -> dict:
        """Load configuration from YAML file"""
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            logger.info(f"Loaded configuration from {self.config_path}")
            return config
        except Exception as e:
            logger.error(f"Error loading config: {e}. Using defaults.")
            return self._default_config()
    
    def _default_config(self) -> dict:
        """Return default configuration"""
        return {
            "scraper": {
                "schedule": {"hour": 9, "minute": 0},
                "max_jobs_per_day": 50,
                "enabled": True
            },
            "enricher": {
                "schedule": {"minute": 0},
                "max_retries": 3,
                "batch_size": 10,
                "enabled": True
            },
            "generator": {
                "schedule": {"minute": 30},
                "max_retries": 3,
                "batch_size": 10,
                "enabled": True
            },
            "daemon": {
                "log_file": "logs/pipeline.log",
                "pid_file": ".pipeline.pid",
                "log_level": "INFO"
            }
        }
    
    async def scrape_jobs_task(self):
        """Scheduled task for scraping jobs"""
        if not self.config["scraper"]["enabled"]:
            logger.debug("Scraper is disabled, skipping")
            return
        
        try:
            logger.info("=" * 60)
            logger.info(f"Running scheduled scrape_jobs task at {datetime.now()}")
            logger.info("=" * 60)
            
            max_jobs = self.config["scraper"]["max_jobs_per_day"]
            keywords = os.getenv("JOB_KEYWORDS")
            location = os.getenv("JOB_LOCATION")
            
            count = await scrape_jobs_stage(
                max_jobs=max_jobs,
                keywords=keywords,
                location=location
            )
            logger.info(f"Scrape task completed: {count} jobs scraped")
        except Exception as e:
            logger.error(f"Error in scrape_jobs_task: {e}", exc_info=True)
    
    async def enrich_companies_task(self):
        """Scheduled task for enriching companies"""
        if not self.config["enricher"]["enabled"]:
            logger.debug("Enricher is disabled, skipping")
            return
        
        try:
            logger.info("=" * 60)
            logger.info(f"Running scheduled enrich_companies task at {datetime.now()}")
            logger.info("=" * 60)
            
            batch_size = self.config["enricher"]["batch_size"]
            max_retries = self.config["enricher"]["max_retries"]
            
            count = await enrich_companies_stage(
                batch_size=batch_size,
                max_retries=max_retries
            )
            logger.info(f"Enrich task completed: {count} companies enriched")
        except Exception as e:
            logger.error(f"Error in enrich_companies_task: {e}", exc_info=True)
    
    async def generate_drafts_task(self):
        """Scheduled task for generating drafts"""
        if not self.config["generator"]["enabled"]:
            logger.debug("Generator is disabled, skipping")
            return
        
        try:
            logger.info("=" * 60)
            logger.info(f"Running scheduled generate_drafts task at {datetime.now()}")
            logger.info("=" * 60)
            
            batch_size = self.config["generator"]["batch_size"]
            max_retries = self.config["generator"]["max_retries"]
            
            count = await generate_drafts_stage(
                batch_size=batch_size,
                max_retries=max_retries
            )
            logger.info(f"Generate task completed: {count} drafts generated")
        except Exception as e:
            logger.error(f"Error in generate_drafts_task: {e}", exc_info=True)
    
    def setup_schedules(self):
        """Configure scheduled tasks"""
        # Scraper schedule
        if self.config["scraper"]["enabled"]:
            scraper_schedule = self.config["scraper"]["schedule"]
            self.scheduler.add_job(
                lambda: _run_async(self.scrape_jobs_task()),
                CronTrigger(
                    hour=scraper_schedule.get("hour", 9),
                    minute=scraper_schedule.get("minute", 0)
                ),
                id='scrape_jobs',
                name='Scrape Jobs',
                replace_existing=True
            )
            logger.info(f"Scheduled scraper: daily at {scraper_schedule.get('hour', 9):02d}:{scraper_schedule.get('minute', 0):02d}")
        
        # Enricher schedule
        if self.config["enricher"]["enabled"]:
            enricher_schedule = self.config["enricher"]["schedule"]
            self.scheduler.add_job(
                lambda: _run_async(self.enrich_companies_task()),
                CronTrigger(
                    hour=enricher_schedule.get("hour"),
                    minute=enricher_schedule.get("minute", 0)
                ),
                id='enrich_companies',
                name='Enrich Companies',
                replace_existing=True
            )
            schedule_desc = f"every hour at :{enricher_schedule.get('minute', 0):02d}"
            if "hour" in enricher_schedule:
                schedule_desc = f"at {enricher_schedule['hour']:02d}:{enricher_schedule.get('minute', 0):02d}"
            logger.info(f"Scheduled enricher: {schedule_desc}")
        
        # Generator schedule
        if self.config["generator"]["enabled"]:
            generator_schedule = self.config["generator"]["schedule"]
            self.scheduler.add_job(
                lambda: _run_async(self.generate_drafts_task()),
                CronTrigger(
                    hour=generator_schedule.get("hour"),
                    minute=generator_schedule.get("minute", 30)
                ),
                id='generate_drafts',
                name='Generate Drafts',
                replace_existing=True
            )
            schedule_desc = f"every hour at :{generator_schedule.get('minute', 30):02d}"
            if "hour" in generator_schedule:
                schedule_desc = f"at {generator_schedule['hour']:02d}:{generator_schedule.get('minute', 30):02d}"
            logger.info(f"Scheduled generator: {schedule_desc}")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals - just set event, main thread does cleanup"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        self._shutdown_event.set()
    
    def shutdown(self):
        """Clean shutdown"""
        logger.info("Shutting down scheduler...")
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
        
        if self.pid_file.exists():
            self.pid_file.unlink()
            logger.info("Removed PID file")
        
        logger.info("Daemon shutdown complete")
    
    def write_pid_file(self):
        """Write PID file"""
        try:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.pid_file, 'w') as f:
                f.write(str(os.getpid()))
            logger.info(f"Wrote PID file: {self.pid_file}")
        except Exception as e:
            logger.error(f"Error writing PID file: {e}")
            raise
    
    def check_and_cleanup_pid(self):
        """Check for existing daemon and cleanup stale PID files"""
        if self.pid_file.exists():
            try:
                with open(self.pid_file, 'r') as f:
                    old_pid = int(f.read().strip())
                # Check if process is still running
                try:
                    os.kill(old_pid, 0)  # Signal 0 just checks if process exists
                    logger.error(f"Daemon already running with PID {old_pid}")
                    sys.exit(1)
                except ProcessLookupError:
                    # Process doesn't exist, remove stale PID file
                    logger.warning(f"Removing stale PID file (PID {old_pid} not found)")
                    self.pid_file.unlink()
            except (ValueError, FileNotFoundError):
                # Invalid PID file, remove it
                if self.pid_file.exists():
                    self.pid_file.unlink()

    def run(self):
        """Start daemon"""
        # Note: Start script handles "already running" - don't check here to avoid race
        # where start script writes PID before we run, causing false "already running"
        self.write_pid_file()
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)  # Ignore SIGHUP (prevents exit when shell closes)
        self.setup_schedules()
        logger.info("Starting pipeline daemon...")
        logger.info(f"PID: {os.getpid()}")
        logger.info(f"Log file: {self.log_file}")
        self.scheduler.start()
        try:
            logger.info("Pipeline daemon is running. Press Ctrl+C to stop.")
            self._shutdown_event.wait()  # Block until shutdown signal
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutdown signal received")
        finally:
            self.shutdown()


def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Pipeline daemon")
    parser.add_argument(
        "--config",
        type=str,
        help="Path to configuration file (default: scripts/pipeline_config.yaml)"
    )
    
    args = parser.parse_args()
    
    daemon = PipelineDaemon(config_path=args.config)
    daemon.run()


if __name__ == "__main__":
    main()
