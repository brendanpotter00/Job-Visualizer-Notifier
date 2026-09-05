"""Stage A — deterministic description cleaning (NO LLM).

bs4 unwrap -> html2text -> cut EEO/benefits/"about us" boilerplate -> collapse
whitespace. Pure and idempotent: the stable artifact the judge scores against.
Store the FULL clean_description; feed agents a copy truncated to a token budget.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

try:
    import html2text as _html2text
except Exception:  # pragma: no cover - optional at import time
    _html2text = None

# ~6000 chars ≈ 1500 tokens; descriptions run 12–18k chars in production.
DEFAULT_CHAR_BUDGET = 6000

# Only cut a boilerplate section once we've seen this much real content before
# it, so a company intro at the very TOP (some ATS lead with "About us") is
# preserved while a TRAILING EEO/benefits/about block is dropped.
_MIN_PREFIX_CHARS = 300

_BOILERPLATE_HEADERS = (
    "equal opportunity", "equal employment", "eeo", "e-verify",
    "we are an equal", "reasonable accommodation", "accommodation request",
    "benefits", "perks", "compensation range", "pay range", "salary range",
    "what we offer", "our benefits", "why join", "why work",
    "about us", "about the company", "who we are", "our mission",
    "privacy policy", "applicant privacy", "to all recruitment agencies",
    "background check", "at will",
)

_WS_RE = re.compile(r"[ \t]+")
_MULTINEWLINE_RE = re.compile(r"\n{3,}")

# A body stored DOUBLE-escaped: real block-level tags that arrived as entity TEXT
# ("&lt;li&gt;") instead of markup, so one unescaping pass turns them into live
# tags rather than removing them. Deliberately keyed on a closed list of real HTML
# tag names in the INPUT — not on "the output still has angle brackets", which
# also fires on ordinary prose like `Promise&lt;T&gt;` or `&lt;Button /&gt;` and
# would then delete it.
_DOUBLE_ESCAPED_TAG_RE = re.compile(
    r"&lt;/?(?:p|div|span|br|hr|li|ul|ol|dl|dd|dt|h[1-6]|table|thead|tbody|tr|td|th"
    r"|strong|em|b|i|u|a|img|section|article|header|footer|blockquote|pre|code)\b",
    re.IGNORECASE,
)


def _to_markdown(description_html: str | None) -> str:
    if not description_html:
        return ""
    soup = BeautifulSoup(description_html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    unwrapped = str(soup)
    if _html2text is not None:
        h = _html2text.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.body_width = 0
        return h.handle(unwrapped)
    return soup.get_text("\n")


def _is_boilerplate_header(line: str) -> bool:
    low = line.strip().lstrip("#").strip().lower()
    if not low or len(low) > 80:
        return False
    return any(low.startswith(h) for h in _BOILERPLATE_HEADERS)


def _cut_boilerplate(text: str) -> str:
    """Drop the first boilerplate section (and everything after it) that appears
    once past the top intro. Character-based so it works on short and long docs."""
    lines = text.split("\n")
    prefix_chars = 0
    for i, line in enumerate(lines):
        if _is_boilerplate_header(line) and prefix_chars >= _MIN_PREFIX_CHARS:
            return "\n".join(lines[:i]).rstrip()
        prefix_chars += len(line) + 1
    return text


def clean_description(description_html: str | None) -> str:
    md = _to_markdown(description_html)
    # Some ATS rows store the body DOUBLE-escaped (Greenhouse serves Vercel's
    # postings as "&lt;li ...&gt;"), so the first pass UNESCAPES the entities into
    # literal tags instead of stripping them and the classifier gets markup as
    # prose. Re-run the pass ONCE for exactly those rows — bounded, so no loop.
    #
    # The trigger is the INPUT carrying escaped real tags, NOT "the output still
    # has angle brackets". Keying on the output looks equivalent and is not: it
    # also fires on postings that merely mention `Promise<T>` or `<Button />`,
    # and pass 2 then DELETES them. Worse, when pass 1's output is ordinary
    # markdown, feeding it back to html2text collapses every newline — which
    # silently disables `_cut_boilerplate` below (it is line-based and skips
    # lines >80 chars), so EEO/benefits boilerplate survives into the classifier.
    if _DOUBLE_ESCAPED_TAG_RE.search(description_html or ""):
        md = _to_markdown(md)
    md = _cut_boilerplate(md)
    md = _WS_RE.sub(" ", md)
    md = _MULTINEWLINE_RE.sub("\n\n", md)
    return md.strip()


def truncate_for_agent(clean_text: str, char_budget: int = DEFAULT_CHAR_BUDGET) -> str:
    if len(clean_text) <= char_budget:
        return clean_text
    head = clean_text[:char_budget]
    cut = max(head.rfind("\n\n"), head.rfind(". "))
    if cut > char_budget * 0.6:
        head = head[: cut + 1]
    return head.rstrip() + "\n\n[…truncated for classification…]"


def has_residual_html(text: str) -> bool:
    """Eval sanity check: cleaned text should contain no HTML tags."""
    return bool(re.search(r"<[a-zA-Z/][^>]*>", text))
