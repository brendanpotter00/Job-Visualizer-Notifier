"""
Shared utility functions for scrapers
"""

import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def get_iso_timestamp() -> str:
    """Get current timestamp in ISO 8601 format (UTC) with microsecond precision"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
