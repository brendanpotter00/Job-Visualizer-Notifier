"""
Utility functions for Google Jobs scraper
"""

import asyncio
import random
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from .config import (
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    MAX_RETRIES,
    RETRY_MIN_WAIT,
    RETRY_MAX_WAIT,
    CHECKPOINT_FILE,
)
from .models import CheckpointData

# Set up logging
logger = logging.getLogger(__name__)


async def random_delay():
    """Add random delay between requests to avoid detection"""
    delay = random.uniform(REQUEST_DELAY_MIN, REQUEST_DELAY_MAX)
    logger.debug(f"Waiting {delay:.2f} seconds before next request")
    await asyncio.sleep(delay)


def setup_logging(verbose: bool = False):
    """Configure logging for the scraper"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_retry_decorator():
    """Get retry decorator for network requests"""
    return retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=RETRY_MIN_WAIT, max=RETRY_MAX_WAIT),
        retry=retry_if_exception_type((TimeoutError, ConnectionError, Exception)),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def save_checkpoint(checkpoint_data: CheckpointData, filepath: Optional[str] = None):
    """Save checkpoint data to file"""
    filepath = filepath or CHECKPOINT_FILE
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    with open(filepath, "w") as f:
        json.dump(checkpoint_data.model_dump(), f, indent=2)

    logger.info(f"Checkpoint saved: {len(checkpoint_data.jobs)} jobs, {filepath}")


def load_checkpoint(filepath: Optional[str] = None) -> Optional[CheckpointData]:
    """Load checkpoint data from file"""
    filepath = filepath or CHECKPOINT_FILE

    if not Path(filepath).exists():
        logger.info("No checkpoint file found, starting fresh")
        return None

    try:
        with open(filepath, "r") as f:
            data = json.load(f)
        checkpoint = CheckpointData(**data)
        logger.info(
            f"Checkpoint loaded: {len(checkpoint.jobs)} jobs, "
            f"{len(checkpoint.completed_queries)} queries completed"
        )
        return checkpoint
    except Exception as e:
        logger.error(f"Error loading checkpoint: {e}")
        return None


def delete_checkpoint(filepath: Optional[str] = None):
    """Delete checkpoint file after successful completion"""
    filepath = filepath or CHECKPOINT_FILE
    try:
        Path(filepath).unlink(missing_ok=True)
        logger.info("Checkpoint file deleted")
    except Exception as e:
        logger.warning(f"Could not delete checkpoint file: {e}")


def get_iso_timestamp() -> str:
    """Get current timestamp in ISO 8601 format"""
    return datetime.utcnow().isoformat() + "Z"


def extract_job_id_from_url(url: str) -> Optional[str]:
    """
    Extract job ID from URL
    Example: "jobs/results/74939955737961158-software-engineer-iii-google-cloud"
    Returns: "74939955737961158"
    """
    try:
        if "/jobs/results/" in url:
            # Extract the part after /jobs/results/
            job_part = url.split("/jobs/results/")[1]
            # Job ID is everything before the first hyphen
            job_id = job_part.split("-")[0]
            return job_id
        return None
    except Exception as e:
        logger.warning(f"Could not extract job ID from URL {url}: {e}")
        return None


def should_include_job(title: str, include_keywords: list, exclude_keywords: list) -> bool:
    """
    Check if a job title should be included based on keyword filters
    """
    title_lower = title.lower()

    # Check for exclusion keywords first
    has_exclude = any(kw.lower() in title_lower for kw in exclude_keywords)
    if has_exclude:
        return False

    # Check for inclusion keywords
    has_include = any(kw.lower() in title_lower for kw in include_keywords)
    return has_include


def ensure_output_directory(output_path: str):
    """Ensure output directory exists"""
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
