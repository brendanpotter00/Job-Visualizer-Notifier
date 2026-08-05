"""Discovery-side helper: dump the shape of a page's embedded JSON island.

Usage: python inspect_embedded.py <captures/<target>/page.html> <css-selector> <attribute>
"""

from __future__ import annotations

import json
import sys

from bs4 import BeautifulSoup

from capture import find_record_arrays


def main() -> None:
    html_path, selector = sys.argv[1], sys.argv[2]
    attribute = sys.argv[3] if len(sys.argv) > 3 else None

    soup = BeautifulSoup(open(html_path).read(), "html.parser")
    node = soup.select_one(selector)
    if node is None:
        raise SystemExit(f"selector {selector!r} matched nothing")

    blob = node.get(attribute) if attribute else node.get_text()
    payload = json.loads(blob, strict=False)

    arrays = find_record_arrays(payload)
    arrays.sort(key=lambda a: (a["job_score"], a["count"]), reverse=True)
    print(json.dumps({
        "top_level_keys": sorted(payload.keys()) if isinstance(payload, dict) else "<list>",
        "record_arrays": arrays[:4],
    }, indent=2)[:4000])


if __name__ == "__main__":
    main()
