"""
scheduler.py — Searchy Scheduler
Runs the full pipeline automatically 4x per day.
"""

import schedule
import time
import logging
import subprocess
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


from pathlib import Path

def get_searchy_root() -> Path:
    return Path(__file__).resolve().parent

def run_pipeline():
    logger.info("Scheduler triggering pipeline...")
    root = get_searchy_root()
    result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=str(root),
    )
    if result.returncode == 0:
        logger.info("Pipeline completed successfully.")
    else:
        logger.error("Pipeline failed with code %s", result.returncode)


if __name__ == "__main__":
    logger.info("Searchy Scheduler started — runs at 08:00, 12:00, 18:00, 23:00")

    schedule.every().day.at("08:00").do(run_pipeline)
    schedule.every().day.at("12:00").do(run_pipeline)
    schedule.every().day.at("18:00").do(run_pipeline)
    schedule.every().day.at("23:00").do(run_pipeline)

    # Run once immediately on start
    run_pipeline()

    while True:
        schedule.run_pending()
        time.sleep(30)