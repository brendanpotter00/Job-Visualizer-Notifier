"""Unit tests for Apple pagination detection (check_has_next_page, get_total_pages).

These pin the CONTRACT that broke on 2026-08-28: Apple's "Next" control is an
icon-only chevron button with empty text and its label in ``aria-label``, so a
text-content selector matched nothing and the scraper stopped after page 1.
See docs/incidents/2026-08-28-apple-pagination-single-page.md.

Fast + browser-free (mocked Playwright). The companion real-DOM pin that runs
``check_has_next_page`` against Apple's ACTUAL captured markup through a real
Playwright engine lives in ``tests/e2e/test_apple_pagination_markup_e2e.py``
(marked ``e2e``; run with ``pytest -m e2e``).
"""

import pytest
import sys
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apple_jobs_scraper.parser import check_has_next_page, get_total_pages


def _button(*, disabled, aria_disabled):
    """A mock <button> whose get_attribute answers PER attribute name.

    The real fix reads two attributes (``disabled`` and ``aria-disabled``); a
    blanket get_attribute mock would not distinguish them, so this returns the
    right value for each name and None for anything else.
    """
    btn = AsyncMock()

    async def get_attribute(name):
        return {"disabled": disabled, "aria-disabled": aria_disabled}.get(name)

    btn.get_attribute = AsyncMock(side_effect=get_attribute)
    return btn


def _page_returning(element):
    page = AsyncMock()
    page.query_selector = AsyncMock(return_value=element)
    return page


class TestCheckHasNextPageAriaLabel:
    """The fix selects by aria-label, not by text content."""

    @pytest.mark.asyncio
    async def test_queries_by_aria_label_not_text(self):
        """Regression guard: the selector must be the aria-label one.

        If anyone reverts to ``button:has-text("Next Page")`` (the bug), this
        assertion fails — the whole point of the incident.
        """
        page = _page_returning(_button(disabled=None, aria_disabled=None))

        await check_has_next_page(page)

        page.query_selector.assert_awaited_once_with('button[aria-label="Next Page"]')

    @pytest.mark.asyncio
    async def test_enabled_next_button_returns_true(self):
        """Page 1..N-1: button present, neither disabled encoding set -> True."""
        page = _page_returning(_button(disabled=None, aria_disabled=None))
        assert await check_has_next_page(page) is True

    @pytest.mark.asyncio
    async def test_disabled_empty_string_returns_false(self):
        """Last page: Apple sets disabled="" (a FALSY empty string) -> False.

        The old code tested ``is_disabled is None``; this pins that an empty
        string still counts as disabled.
        """
        page = _page_returning(_button(disabled="", aria_disabled="true"))
        assert await check_has_next_page(page) is False

    @pytest.mark.asyncio
    async def test_aria_disabled_only_returns_false(self):
        """aria-disabled="true" alone (no ``disabled`` attr) still stops the walk."""
        page = _page_returning(_button(disabled=None, aria_disabled="true"))
        assert await check_has_next_page(page) is False

    @pytest.mark.asyncio
    async def test_no_button_returns_false(self):
        page = _page_returning(None)
        assert await check_has_next_page(page) is False

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(side_effect=Exception("page crashed"))
        assert await check_has_next_page(page) is None


class TestGetTotalPages:
    """The board-size oracle used for the loud-truncation cross-check."""

    @pytest.mark.asyncio
    async def test_reads_integer(self):
        el = AsyncMock()
        el.text_content = AsyncMock(return_value="226")
        assert await get_total_pages(_page_returning(el)) == 226

    @pytest.mark.asyncio
    async def test_strips_commas_and_whitespace(self):
        el = AsyncMock()
        el.text_content = AsyncMock(return_value="  1,226 ")
        assert await get_total_pages(_page_returning(el)) == 1226

    @pytest.mark.asyncio
    async def test_missing_element_returns_none(self):
        assert await get_total_pages(_page_returning(None)) is None

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self):
        el = AsyncMock()
        el.text_content = AsyncMock(return_value="")
        assert await get_total_pages(_page_returning(el)) is None

    @pytest.mark.asyncio
    async def test_non_numeric_returns_none(self):
        el = AsyncMock()
        el.text_content = AsyncMock(return_value="Of")
        assert await get_total_pages(_page_returning(el)) is None

    @pytest.mark.asyncio
    async def test_exception_returns_none(self):
        page = AsyncMock()
        page.query_selector = AsyncMock(side_effect=Exception("boom"))
        assert await get_total_pages(page) is None
