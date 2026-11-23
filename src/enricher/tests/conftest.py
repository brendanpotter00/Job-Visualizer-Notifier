import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest

from job_enricher.store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(db_path=tmp_path / "t.db")
    s.init_schema()
    return s
