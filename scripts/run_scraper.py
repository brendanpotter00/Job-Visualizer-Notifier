#!/usr/bin/env python
"""
Convenience script to run the Google Jobs scraper
"""

import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import and run main
from scripts.google_jobs_scraper.main import main

if __name__ == "__main__":
    main()
