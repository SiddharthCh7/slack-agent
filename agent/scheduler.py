"""Scheduler for running the OLake LinkedIn Marketing Agent on a schedule.

Runs the agent at configurable intervals.
"""

import time
import signal
import sys
from datetime import datetime
from loguru import logger

from agent.config import setup_logging
from agent.main import run_agent


# Default interval: 1 hour
DEFAULT_INTERVAL_SECONDS = 3600

# Flag for graceful shutdown
running = True


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully."""
    global running
    logger.info(f"Received signal {signum}, shutting down gracefully...")
    running = False


def run_scheduler(interval_seconds: int = DEFAULT_INTERVAL_SECONDS):
    """Run the agent on a schedule.
    
    Args:
        interval_seconds: Time between runs in seconds
    """
    global running
    
    # Setup signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Setup logging
    setup_logging()
    
    logger.info("=" * 60)
    logger.info("🕐 OLake LinkedIn Marketing Agent Scheduler Started")
    logger.info(f"   Interval: {interval_seconds} seconds ({interval_seconds/60:.1f} minutes)")
    logger.info("   Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    run_count = 0
    total_comments = 0
    
    while running:
        run_count += 1
        logger.info(f"\n🔄 Starting run #{run_count} at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        try:
            result = run_agent()
            total_comments += result.get("comments_posted", 0)
            
            logger.info(f"Run #{run_count} complete. Total comments so far: {total_comments}")
            
        except Exception as e:
            logger.error(f"Run #{run_count} failed with exception: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        if running:
            logger.info(f"💤 Sleeping for {interval_seconds} seconds until next run...")
            
            # Sleep in small increments to allow for graceful shutdown
            sleep_increment = 10
            remaining = interval_seconds
            
            while remaining > 0 and running:
                sleep_time = min(sleep_increment, remaining)
                time.sleep(sleep_time)
                remaining -= sleep_time
    
    logger.info("\n" + "=" * 60)
    logger.info("🛑 Scheduler stopped gracefully")
    logger.info(f"   Total runs: {run_count}")
    logger.info(f"   Total comments: {total_comments}")
    logger.info("=" * 60)


def main():
    """CLI entry point for the scheduler."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="OLake LinkedIn Marketing Agent Scheduler",
    )
    
    parser.add_argument(
        "--interval",
        type=int,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Interval between runs in seconds (default: {DEFAULT_INTERVAL_SECONDS})"
    )
    
    args = parser.parse_args()
    
    run_scheduler(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
