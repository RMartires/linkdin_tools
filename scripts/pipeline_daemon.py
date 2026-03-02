"""Pipeline daemon with APScheduler for scheduled job processing"""

import asyncio
import os
import signal
import sys
import threading
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional
from dotenv import load_dotenv

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

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
        self.api_server = None
        self.api_thread = None
        
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
            },
            "api": {
                "enabled": True,
                "port": 8000,
                "host": "127.0.0.1"
            }
        }
    
    async def scrape_jobs_task(self):
        """Scheduled task for scraping jobs with multiple configurations"""
        if not self.config["scraper"]["enabled"]:
            logger.debug("Scraper is disabled, skipping")
            return
        
        try:
            logger.info("=" * 60)
            logger.info(f"Running scheduled scrape_jobs task at {datetime.now()}")
            logger.info("=" * 60)
            
            scraper_config = self.config["scraper"]
            search_configs = scraper_config.get("search_configs", [])
            delay_between_runs = scraper_config.get("delay_between_runs", 30)
            default_max_jobs = scraper_config.get("max_jobs_per_day", 50)
            
            # If search_configs is provided, iterate through them
            if search_configs:
                total_scraped = 0
                for idx, config in enumerate(search_configs, 1):
                    title = config.get("title")
                    location = config.get("location")
                    max_jobs = config.get("max_jobs", default_max_jobs)
                    
                    if not title:
                        logger.warning(f"Skipping search config {idx}: missing 'title' field")
                        continue
                    
                    logger.info(f"Running scrape {idx}/{len(search_configs)}: title='{title}', location='{location or 'None'}', max_jobs={max_jobs}")
                    
                    try:
                        count = await scrape_jobs_stage(
                            max_jobs=max_jobs,
                            keywords=title,
                            location=location
                        )
                        total_scraped += count
                        logger.info(f"Scrape {idx} completed: {count} jobs scraped")
                    except Exception as e:
                        logger.error(f"Error in scrape {idx}: {e}", exc_info=True)
                    
                    # Delay between runs (except after last one)
                    if idx < len(search_configs):
                        logger.info(f"Waiting {delay_between_runs} seconds before next scrape...")
                        await asyncio.sleep(delay_between_runs)
                
                logger.info(f"All scrape tasks completed: {total_scraped} total jobs scraped")
            else:
                # Fallback to env vars (backward compatibility)
                keywords = os.getenv("JOB_KEYWORDS")
                location = os.getenv("JOB_LOCATION")
                count = await scrape_jobs_stage(
                    max_jobs=default_max_jobs,
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
            minute_val = enricher_schedule.get('minute', 0)
            if isinstance(minute_val, str):
                schedule_desc = f"every hour (minute={minute_val})"
            elif "hour" in enricher_schedule:
                schedule_desc = f"at {enricher_schedule['hour']:02d}:{minute_val:02d}"
            else:
                schedule_desc = f"every hour at :{minute_val:02d}"
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
            minute_val = generator_schedule.get('minute', 30)
            if isinstance(minute_val, str):
                schedule_desc = f"every hour (minute={minute_val})"
            elif "hour" in generator_schedule:
                schedule_desc = f"at {generator_schedule['hour']:02d}:{minute_val:02d}"
            else:
                schedule_desc = f"every hour at :{minute_val:02d}"
            logger.info(f"Scheduled generator: {schedule_desc}")
    
    def signal_handler(self, signum, frame):
        """Handle shutdown signals - just set event, main thread does cleanup"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        self._shutdown_event.set()
    
    def setup_api_server(self):
        """Setup FastAPI server for manual triggers"""
        api_config = self.config.get("api", {})
        if not api_config.get("enabled", True):
            logger.info("API server is disabled")
            return
        
        app = FastAPI(title="Pipeline Daemon API", description="API for manually triggering pipeline stages")
        
        @app.get("/")
        async def root():
            return {
                "message": "Pipeline Daemon API",
                "endpoints": {
                    "trigger_scrape": "/api/trigger/scrape",
                    "trigger_enrich": "/api/trigger/enrich",
                    "trigger_generate": "/api/trigger/generate",
                    "health": "/api/health"
                }
            }
        
        @app.get("/api/health")
        async def health():
            return {
                "status": "healthy",
                "daemon_running": self.running,
                "scheduler_running": self.scheduler.running if hasattr(self.scheduler, 'running') else False
            }
        
        @app.post("/api/trigger/scrape")
        async def trigger_scrape(
            keywords: Optional[str] = None,
            location: Optional[str] = None,
            max_jobs: Optional[int] = None
        ):
            """Manually trigger job scraping"""
            try:
                logger.info(f"Manual scrape trigger: keywords={keywords}, location={location}, max_jobs={max_jobs}")
                
                # Use provided params or fall back to config/env
                scraper_config = self.config["scraper"]
                max_jobs_to_scrape = max_jobs or scraper_config.get("max_jobs_per_day", 50)
                search_keywords = keywords or os.getenv("JOB_KEYWORDS")
                search_location = location or os.getenv("JOB_LOCATION")
                
                # Run in background thread
                def run_scrape():
                    asyncio.run(self.scrape_jobs_task_manual(
                        keywords=search_keywords,
                        location=search_location,
                        max_jobs=max_jobs_to_scrape
                    ))
                threading.Thread(target=run_scrape, daemon=True).start()
                
                return {
                    "status": "triggered",
                    "message": "Scrape job started",
                    "params": {
                        "keywords": search_keywords,
                        "location": search_location,
                        "max_jobs": max_jobs_to_scrape
                    }
                }
            except Exception as e:
                logger.error(f"Error triggering scrape: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @app.post("/api/trigger/enrich")
        async def trigger_enrich(
            batch_size: Optional[int] = None,
            max_retries: Optional[int] = None
        ):
            """Manually trigger company enrichment"""
            try:
                logger.info(f"Manual enrich trigger: batch_size={batch_size}, max_retries={max_retries}")
                
                enricher_config = self.config["enricher"]
                batch = batch_size or enricher_config.get("batch_size", 10)
                retries = max_retries or enricher_config.get("max_retries", 3)
                
                # Run in background thread
                def run_enrich():
                    asyncio.run(self.enrich_companies_task_manual(
                        batch_size=batch,
                        max_retries=retries
                    ))
                threading.Thread(target=run_enrich, daemon=True).start()
                
                return {
                    "status": "triggered",
                    "message": "Enrich job started",
                    "params": {
                        "batch_size": batch,
                        "max_retries": retries
                    }
                }
            except Exception as e:
                logger.error(f"Error triggering enrich: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        @app.post("/api/trigger/generate")
        async def trigger_generate(
            batch_size: Optional[int] = None,
            max_retries: Optional[int] = None
        ):
            """Manually trigger draft generation"""
            try:
                logger.info(f"Manual generate trigger: batch_size={batch_size}, max_retries={max_retries}")
                
                generator_config = self.config["generator"]
                batch = batch_size or generator_config.get("batch_size", 10)
                retries = max_retries or generator_config.get("max_retries", 3)
                
                # Run in background thread
                def run_generate():
                    asyncio.run(self.generate_drafts_task_manual(
                        batch_size=batch,
                        max_retries=retries
                    ))
                threading.Thread(target=run_generate, daemon=True).start()
                
                return {
                    "status": "triggered",
                    "message": "Generate job started",
                    "params": {
                        "batch_size": batch,
                        "max_retries": retries
                    }
                }
            except Exception as e:
                logger.error(f"Error triggering generate: {e}", exc_info=True)
                raise HTTPException(status_code=500, detail=str(e))
        
        self.api_server = app
        return app
    
    def start_api_server(self):
        """Start API server in background thread"""
        api_config = self.config.get("api", {})
        if not api_config.get("enabled", True):
            return
        
        app = self.setup_api_server()
        if not app:
            return
        
        port = api_config.get("port", 8000)
        host = api_config.get("host", "127.0.0.1")
        
        def run_server():
            uvicorn.run(app, host=host, port=port, log_level="info")
        
        self.api_thread = threading.Thread(target=run_server, daemon=True)
        self.api_thread.start()
        logger.info(f"API server started on http://{host}:{port}")
    
    async def scrape_jobs_task_manual(self, keywords: Optional[str] = None, location: Optional[str] = None, max_jobs: int = 50):
        """Manual scrape task (can override params)"""
        try:
            logger.info("=" * 60)
            logger.info(f"Running manual scrape_jobs task at {datetime.now()}")
            logger.info("=" * 60)
            
            count = await scrape_jobs_stage(
                max_jobs=max_jobs,
                keywords=keywords,
                location=location
            )
            logger.info(f"Manual scrape task completed: {count} jobs scraped")
        except Exception as e:
            logger.error(f"Error in manual scrape_jobs_task: {e}", exc_info=True)
    
    async def enrich_companies_task_manual(self, batch_size: int = 10, max_retries: int = 3):
        """Manual enrich task"""
        try:
            logger.info("=" * 60)
            logger.info(f"Running manual enrich_companies task at {datetime.now()}")
            logger.info("=" * 60)
            
            count = await enrich_companies_stage(
                batch_size=batch_size,
                max_retries=max_retries
            )
            logger.info(f"Manual enrich task completed: {count} companies enriched")
        except Exception as e:
            logger.error(f"Error in manual enrich_companies_task: {e}", exc_info=True)
    
    async def generate_drafts_task_manual(self, batch_size: int = 10, max_retries: int = 3):
        """Manual generate task"""
        try:
            logger.info("=" * 60)
            logger.info(f"Running manual generate_drafts task at {datetime.now()}")
            logger.info("=" * 60)
            
            count = await generate_drafts_stage(
                batch_size=batch_size,
                max_retries=max_retries
            )
            logger.info(f"Manual generate task completed: {count} drafts generated")
        except Exception as e:
            logger.error(f"Error in manual generate_drafts_task: {e}", exc_info=True)
    
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
        self.start_api_server()  # Start API server
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
