#!/usr/bin/env python

import time
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

import data_manager

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def safe_job(func):
    """Decorator to catch and log exceptions in scheduled jobs."""
    def wrapper(*args, **kwargs):
        try:
            logging.info(f"Running job: {func.__name__}")
            func(*args, **kwargs)
            logging.info(f"Finished job: {func.__name__}")
        except Exception as e:
            logging.error(f"Error running job {func.__name__}: {e}", exc_info=True)
    return wrapper

@safe_job
def expire_duels_job():
    """Job to handle the expiration of pending duels."""
    data_manager.expire_pending_duels()

@safe_job
def start_leagues_job():
    """Job to handle the starting of scheduled league rounds."""
    data_manager.start_pending_league_rounds()

if __name__ == "__main__":
    # Initialize the database connection pool before starting the scheduler
    logging.info("Initializing database connection for scheduler...")
    data_manager.initialize_database()
    logging.info("Database connection initialized.")

    scheduler = BlockingScheduler()

    # Schedule the duel expiration job to run every 5 minutes
    scheduler.add_job(
        expire_duels_job, 
        trigger=IntervalTrigger(minutes=5), 
        id='expire_duels_job', 
        name='Expire pending duels every 5 minutes', 
        replace_existing=True
    )

    # Schedule the active duel expiration job to run every 5 minutes
    scheduler.add_job(
        safe_job(data_manager.expire_active_duels), 
        trigger=IntervalTrigger(minutes=5), 
        id='expire_active_duels_job', 
        name='Expire active duels every 5 minutes', 
        replace_existing=True
    )

    # Schedule the league round starting job to run every 10 minutes
    scheduler.add_job(
        start_leagues_job, 
        trigger=IntervalTrigger(minutes=10), 
        id='start_leagues_job', 
        name='Start pending league rounds every 10 minutes', 
        replace_existing=True
    )

    # Schedule the league reminder job to run every hour
    scheduler.add_job(
        safe_job(data_manager.send_league_reminders), 
        trigger=IntervalTrigger(hours=1), 
        id='send_league_reminders_job', 
        name='Send league round reminders every hour', 
        replace_existing=True
    )

    # Schedule the final league results job to run every hour
    scheduler.add_job(
        safe_job(data_manager.process_final_league_results), 
        trigger=IntervalTrigger(hours=1), 
        id='process_final_league_results_job', 
        name='Process final league results every hour', 
        replace_existing=True
    )

    # Schedule the fundraiser reminder job to run every hour
    scheduler.add_job(
        safe_job(data_manager.send_fundraiser_reminders), 
        trigger=IntervalTrigger(hours=1), 
        id='send_fundraiser_reminders_job', 
        name='Send fundraiser reminders every hour', 
        replace_existing=True
    )

    # Schedule the fundraiser conclusion job to run every hour
    scheduler.add_job(
        safe_job(data_manager.process_concluded_fundraisers), 
        trigger=IntervalTrigger(hours=1), 
        id='process_concluded_fundraisers_job', 
        name='Process concluded fundraisers every hour', 
        replace_existing=True
    )

    logging.info("Scheduler started. Press Ctrl+C to exit.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
