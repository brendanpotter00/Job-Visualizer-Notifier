# /// script
# requires-python = ">=3.11"
# dependencies = ["psycopg[binary]>=3.1"]
# ///
"""Export this machine's Launch Radar cards to one JSON file (``launch-radar-cards/v1``).

    uv run scripts/launch_radar/export_cards.py [--out PATH] [--source LABEL]

Reads ``DATABASE_URL`` (default: the local ``jvn_launch_radar`` database) and writes every
card whose status is not ``deleted``, oldest first, to
``docs/implementations/launch-radar/data/cards-<UTC date>.json``:

    {"format": "launch-radar-cards/v1", "exported_at": "...Z", "source": "<label>",
     "cards": [{"domain", "status", "posted_at", "payload"}, ...]}

``source`` is a neutral label, ``local`` unless ``--source`` names another (the file is
committed, so it never carries the machine's hostname).

``radar.sh import --file <path>`` then posts the cards to whatever backend ``BACKEND_URL``
points at, with no Parallel calls: the research is already paid for, and each payload's
``cost_usd`` records what it cost. The database is only read. The output names the
database by host and name only, never the connection string or its password, and
nothing from the radar's env file is read or written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

FORMAT = "launch-radar-cards/v1"  # radar.py import (importer.FORMAT) accepts exactly this
DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/jvn_launch_radar"
DEFAULT_SOURCE = "local"  # the export's "source" label unless --source gives one
SOURCE_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "docs" / "implementations" / "launch-radar" / "data"

QUERY = (
    "SELECT domain, status, posted_at, payload FROM launch_radar_cards "
    "WHERE status <> 'deleted' ORDER BY posted_at, domain"
)


def iso(dt: datetime) -> str:
    """UTC ISO 8601 with a ``Z`` (a naive value is taken as UTC)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def default_out(now: datetime) -> Path:
    return DATA_DIR / f"cards-{now.astimezone(timezone.utc).date().isoformat()}.json"


def libpq_url(url: str) -> str:
    """``postgresql+psycopg2://...`` (a SQLAlchemy URL) -> ``postgresql://...``."""
    return re.sub(r"^postgres(?:ql)?\+[a-z0-9_]+://", "postgresql://", url.strip())


def source_label(value: str) -> str:
    """``--source``: a short label (letters, digits, ``.``, ``_``, ``-``; at most 64)."""
    if not SOURCE_LABEL.match(value):
        raise argparse.ArgumentTypeError("a label of letters, digits, '.', '_' or '-' (at most 64 characters)")
    return value


def db_label(url: str) -> str:
    """``host:port/dbname`` for the summary line: never the user or the password."""
    u = urlparse(url)
    port = f":{u.port}" if u.port else ""
    return f"{u.hostname or 'localhost'}{port}/{u.path.lstrip('/') or '?'}"


def redact(text: str, url: str) -> str:
    password = urlparse(url).password
    return text.replace(password, "***") if password else text


def shape_export(rows: Iterable[Mapping[str, Any]], *, exported_at: datetime, source: str) -> dict[str, Any]:
    """Database rows -> the export document. Pure: no I/O.

    Deleted tombstones (``payload`` NULL) are dropped even if a row slips past the
    query, and a live row without an object payload is an error, never written out.
    """
    cards = []
    for row in rows:
        if row["status"] == "deleted":
            continue
        payload = row["payload"]
        if not isinstance(payload, dict):
            raise ValueError(f"card {row['domain']!r} ({row['status']}) has no payload object")
        posted = row["posted_at"]
        cards.append({"domain": row["domain"], "status": row["status"],
                      "posted_at": iso(posted) if isinstance(posted, datetime) else posted,
                      "payload": payload})
    cards.sort(key=lambda c: (c["posted_at"] or "", c["domain"]))
    return {"format": FORMAT, "exported_at": iso(exported_at), "source": source, "cards": cards}


def summary(doc: Mapping[str, Any]) -> str:
    by_status = Counter(c["status"] for c in doc["cards"])
    parts = ", ".join(f"{s} {by_status[s]}" for s in ("new", "saved", "archived") if by_status[s])
    return f"{len(doc['cards'])} card(s)" + (f" ({parts})" if parts else "")


def fetch_rows(database_url: str) -> list[dict[str, Any]]:
    import psycopg  # lazy: the unit tests exercise shape_export without a database driver
    from psycopg.rows import dict_row

    with psycopg.connect(libpq_url(database_url), row_factory=dict_row) as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(QUERY)
            return list(cur.fetchall())


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="export_cards", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path, help="output file (default: docs/implementations/launch-radar/data/"
                                            "cards-<UTC date>.json)")
    p.add_argument("--source", type=source_label, default=DEFAULT_SOURCE,
                   help=f"the export's source label (default: {DEFAULT_SOURCE!r}; never the hostname)")
    args = p.parse_args(argv)

    url = os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL
    now = datetime.now(timezone.utc)
    try:
        rows = fetch_rows(url)
        doc = shape_export(rows, exported_at=now, source=args.source)
    except Exception as e:  # exit 1 with the reason; the URL's password is redacted from it
        print(f"export: reading {db_label(url)} failed: {redact(f'{type(e).__name__}: {e}', url)}",
              file=sys.stderr)
        return 1
    out = args.out or default_out(now)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"export: {summary(doc)} from {db_label(url)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
