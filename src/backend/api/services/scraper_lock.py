"""Shared concurrency guard for scraper operations.

Prevents multiple Playwright subprocesses from running simultaneously.
Used by both the manual trigger-scrape endpoint and the background
auto_scraper_loop.
"""

import asyncio

scraper_lock = asyncio.Lock()
