"""The six board URLs + expected classification — ONE source of truth
(PLAN.md §1, §5). Every API and UI case imports from here rather than
hardcoding a URL, so a board's URL only ever needs to change in one place.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Board:
    #: Case id this board is the subject of (AC-01 .. AC-06).
    case_id: str
    #: Short label for logs/artifacts.
    label: str
    url: str
    #: 'already_public' | 'ats' | 'discovery'
    path: str
    #: Expected outcome, path-dependent:
    #:   already_public -> the PUBLIC company id it should resolve to
    #:   ats            -> the ATS provider it should resolve to
    #:   discovery       -> None (nothing declared up front)
    expect: str | None
    #: Rough sanity band for open-job count, loosely — never an exact
    #: assertion (PLAN.md §5: "Never assert an exact job count.").
    approx_job_count: int | None = None


MICROSOFT = Board(
    case_id="AC-01",
    label="Microsoft",
    url="https://jobs.careers.microsoft.com/global/en/search",
    path="already_public",
    expect="microsoft",
)

AMAZON = Board(
    case_id="AC-02",
    label="Amazon",
    url="https://www.amazon.jobs/en/search",
    path="already_public",
    expect="amazon",
)

CISCO = Board(
    case_id="AC-03",
    label="Cisco",
    url="https://jobs.cisco.com/jobs/SearchJobs/",
    path="ats",
    expect="workday",
    approx_job_count=1246,
)

ATLASSIAN = Board(
    case_id="AC-04",
    label="Atlassian",
    url="https://www.atlassian.com/company/careers/all-jobs",
    path="discovery",
    expect=None,
    approx_job_count=250,
)

JANE_STREET = Board(
    case_id="AC-05",
    label="Jane Street",
    url="https://www.janestreet.com/join-jane-street/open-roles/",
    path="discovery",
    expect=None,
    approx_job_count=235,
)

SPOTIFY = Board(
    case_id="AC-06",
    label="Spotify",
    url="https://www.lifeatspotify.com/jobs",
    # CHANGED with the company-name dedupe (AC-13). This URL's FIRST answer is now
    # ``already_public`` — the add path reads ``spotify`` out of ``lifeatspotify`` and
    # links to the public page before spending a discovery, which is the entire point
    # of that unit. AC-06 still needs a real discovery of this board to have anything
    # to run the title-overlap matcher against, so it reaches one the way a user would:
    # through the "This isn't the same company" correction (``trackAnyway``).
    path="already_public",
    expect="spotify",
    approx_job_count=85,
)

ALL_BOARDS: tuple[Board, ...] = (
    MICROSOFT,
    AMAZON,
    CISCO,
    ATLASSIAN,
    JANE_STREET,
    SPOTIFY,
)

ALL_URLS: tuple[str, ...] = tuple(b.url for b in ALL_BOARDS)


if __name__ == "__main__":
    # `python -m` (from the add-companies dir, or via boards.py's own path) with
    # `--json` dumps the board table so the UI tier (Playwright/TypeScript) can
    # read the SAME source of truth instead of re-declaring URLs — see
    # `ui/boards.ts`.
    import json
    import sys
    from dataclasses import asdict

    if "--json" in sys.argv:
        print(json.dumps([asdict(b) for b in ALL_BOARDS]))
    else:
        for b in ALL_BOARDS:
            print(f"{b.case_id}\t{b.label}\t{b.url}")
