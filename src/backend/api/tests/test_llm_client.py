"""Unit tests for the Tier-2 Claude Haiku client. All Anthropic calls mocked.

Mock seam patches ``api.services.llm_client.AsyncAnthropic``. Async tests use the
module-level ``pytestmark = pytest.mark.asyncio`` (backend has no asyncio_mode=auto).

PATH A (structured outputs via ``output_config``) was shipped — verified by Step 0
against anthropic 0.107.1, which exposes ``output_config`` as a typed parameter on
``AsyncMessages.create``. ``_resp`` therefore emits a text block carrying the JSON
envelope (the PATH A response shape).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import anthropic
import pytest

from api.config import settings
from api.services.llm_client import (
    CanonicalLocation,
    parse_locations_text,
    LocationLLMError,
    MissingAnthropicKeyError,
    normalize_location_via_llm,
)

pytestmark = pytest.mark.asyncio


def _text_block(text: str):
    return SimpleNamespace(type="text", text=text)


def _resp(locations: list[dict]):
    """PATH A (structured outputs): one text block carrying the JSON envelope."""
    payload = json.dumps({"locations": locations})
    return SimpleNamespace(content=[_text_block(payload)], stop_reason="end_turn")


def _install_mock_client(monkeypatch, *, create_return=None, create_side_effect=None):
    create_mock = AsyncMock()
    if create_side_effect is not None:
        create_mock.side_effect = create_side_effect
    else:
        create_mock.return_value = create_return
    fake_client = MagicMock()
    fake_client.messages.create = create_mock
    constructor_mock = MagicMock(return_value=fake_client)
    monkeypatch.setattr("api.services.llm_client.AsyncAnthropic", constructor_mock)
    return constructor_mock, create_mock


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


async def test_single_location_parse(monkeypatch):
    _, create_mock = _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "San Francisco, CA, US", "kind": "city", "city": "San Francisco",
        "region": "CA", "country": "US", "remote_scope": None, "confidence": 0.97,
    }]))
    result = await normalize_location_via_llm("San Francisco, CA")
    assert len(result) == 1
    loc = result[0]
    assert isinstance(loc, CanonicalLocation)
    assert loc.canonical_name == "San Francisco, CA, US"
    assert loc.kind == "city"
    assert loc.confidence == 0.97
    assert not hasattr(loc, "lat")
    assert not hasattr(loc, "lng")
    create_mock.assert_awaited_once()


async def test_multi_location_parse(monkeypatch):
    _install_mock_client(monkeypatch, create_return=_resp([
        {"canonical_name": "Sunnyvale, CA, US", "kind": "city", "city": "Sunnyvale",
         "region": "CA", "country": "US", "remote_scope": None, "confidence": 0.96},
        {"canonical_name": "Kirkland, WA, US", "kind": "city", "city": "Kirkland",
         "region": "WA", "country": "US", "remote_scope": None, "confidence": 0.95},
    ]))
    result = await normalize_location_via_llm("Sunnyvale, CA, USA; Kirkland, WA, USA")
    assert [l.canonical_name for l in result] == ["Sunnyvale, CA, US", "Kirkland, WA, US"]


async def test_remote_with_scope_parse(monkeypatch):
    _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "Remote (US)", "kind": "remote", "city": None, "region": None,
        "country": None, "remote_scope": "us", "confidence": 0.95,
    }]))
    result = await normalize_location_via_llm("Remote - United States")
    assert result[0].kind == "remote"
    assert result[0].remote_scope == "us"
    assert result[0].city is None


async def test_malformed_non_json_raises(monkeypatch):
    bad = SimpleNamespace(content=[_text_block("not json {{")], stop_reason="end_turn")
    _install_mock_client(monkeypatch, create_return=bad)
    with pytest.raises(LocationLLMError):
        await normalize_location_via_llm("Somewhere")


async def test_schema_violation_raises(monkeypatch):
    _install_mock_client(monkeypatch, create_return=_resp([{"canonical_name": "X"}]))
    with pytest.raises(LocationLLMError):
        await normalize_location_via_llm("X")


async def test_empty_locations_raises(monkeypatch):
    _install_mock_client(monkeypatch, create_return=_resp([]))
    with pytest.raises(LocationLLMError):
        await normalize_location_via_llm("Nowhere")


async def test_bad_kind_raises(monkeypatch):
    _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "Mars Base One", "kind": "planet", "city": None, "region": None,
        "country": None, "remote_scope": None, "confidence": 0.5,
    }]))
    with pytest.raises(LocationLLMError):
        await normalize_location_via_llm("Mars Base One")


async def test_city_with_remote_scope_rejected(monkeypatch):
    # kind='city' carrying a remote_scope violates the cross-field invariant ->
    # ValidationError -> LocationLLMError (Procrastinate retries).
    _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "San Jose, CA, US", "kind": "city", "city": "San Jose",
        "region": "CA", "country": "US", "remote_scope": "us", "confidence": 0.95,
    }]))
    with pytest.raises(LocationLLMError):
        await normalize_location_via_llm("San Jose")


async def test_remote_with_city_rejected(monkeypatch):
    # kind='remote' carrying a city violates the cross-field invariant.
    _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "Remote (US)", "kind": "remote", "city": "San Jose",
        "region": None, "country": None, "remote_scope": "us", "confidence": 0.95,
    }]))
    with pytest.raises(LocationLLMError):
        await normalize_location_via_llm("Remote San Jose")


async def test_remote_with_region_country_scope_accepted(monkeypatch):
    # A region/country-scoped remote keeps its geography: city stays None but
    # region/country carry the scope (prod has 'US - AZ - Remote', etc.).
    _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "Remote (AZ, US)", "kind": "remote", "city": None,
        "region": "AZ", "country": "US", "remote_scope": "us", "confidence": 0.9,
    }]))
    result = await normalize_location_via_llm("US - AZ - Remote")
    loc = result[0]
    assert loc.kind == "remote"
    assert loc.city is None
    assert loc.region == "AZ"
    assert loc.country == "US"
    assert loc.remote_scope == "us"


async def test_remote_with_country_only_scope_accepted(monkeypatch):
    # Country-scoped remote (no sub-national region): country set, region None.
    _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "Remote (Brazil)", "kind": "remote", "city": None,
        "region": None, "country": "BR", "remote_scope": "br", "confidence": 0.9,
    }]))
    result = await normalize_location_via_llm("BR - Brazil - Remote")
    loc = result[0]
    assert loc.kind == "remote"
    assert loc.city is None
    assert loc.region is None
    assert loc.country == "BR"


async def test_confidence_out_of_range_rejected(monkeypatch):
    _install_mock_client(monkeypatch, create_return=_resp([{
        "canonical_name": "San Jose, CA, US", "kind": "city", "city": "San Jose",
        "region": "CA", "country": "US", "remote_scope": None, "confidence": 1.5,
    }]))
    with pytest.raises(LocationLLMError):
        await normalize_location_via_llm("San Jose")


async def test_api_error_propagates(monkeypatch):
    err = anthropic.APIError(message="boom", request=MagicMock(), body=None)
    _install_mock_client(monkeypatch, create_side_effect=err)
    with pytest.raises(anthropic.APIError):
        await normalize_location_via_llm("San Francisco")


async def test_timeout_propagates(monkeypatch):
    err = anthropic.APITimeoutError(request=MagicMock())
    _install_mock_client(monkeypatch, create_side_effect=err)
    with pytest.raises(anthropic.APITimeoutError):
        await normalize_location_via_llm("San Francisco")


async def test_missing_key_raises_and_never_builds_client(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    constructor_mock, create_mock = _install_mock_client(monkeypatch, create_return=_resp([]))
    with pytest.raises(MissingAnthropicKeyError):
        await normalize_location_via_llm("San Francisco")
    constructor_mock.assert_not_called()
    create_mock.assert_not_awaited()


async def test_missing_key_is_subclass_of_location_llm_error():
    assert issubclass(MissingAnthropicKeyError, LocationLLMError)


# --- cardinality guard -------------------------------------------------------

class TestCardinalityGuard:
    """A raw string can only name so many places. "San Francisco" is one; it is
    never ten. Prod had no such check, so an over-generating response was
    accepted whole -- the alias key 'remote' ended up holding 29 locations,
    including Riyadh, for jobs whose raw location was the single word "Remote".
    """

    @staticmethod
    def _payload(n):
        return json.dumps({
            "locations": [
                {
                    "canonical_name": f"City{i}, CA, US", "kind": "city",
                    "city": f"City{i}", "region": "CA", "country": "US",
                    "remote_scope": None, "confidence": 0.9,
                }
                for i in range(n)
            ]
        })

    def test_ceiling_scales_with_separator_groups(self):
        from api.services.llm_client import max_plausible_locations

        assert max_plausible_locations("San Francisco") == 6  # the floor
        assert max_plausible_locations("Sunnyvale, CA, USA; Kirkland, WA, USA") == 6
        assert max_plausible_locations("a, b, c, d, e, f, g, h") == 8

    def test_over_generation_truncates_it_does_not_reject(self):
        """Rejecting was the wrong failure mode.

        A raise retries 5x then marks the job normalization_status='failed' --
        and nothing ever retries a failed job (scan_unnormalized selects IS NULL
        only). So one over-generating raw string left every job carrying it with
        ZERO tags, permanently, invisible in location filters. Too many tags is
        visible and repairable; no tags is neither.
        """
        locs = parse_locations_text(self._payload(10), "San Francisco")
        assert len(locs) == 6
        assert [l.city for l in locs] == [f"City{i}" for i in range(6)]

    def test_a_metro_string_is_not_truncated(self):
        """The floor is 6 so separator-free metros survive: prod has
        'greater seattle area' on 376 OPEN jobs."""
        locs = parse_locations_text(self._payload(4), "greater seattle area")
        assert len(locs) == 4

    def test_genuine_multi_site_posting_is_allowed(self):
        raw = ("Sunnyvale, CA, Los Angeles, CA, Bellevue, WA, Austin, TX, "
               "Seattle, WA, New York, NY")
        locs = parse_locations_text(self._payload(6), raw)
        assert len(locs) == 6

    def test_guard_skipped_when_raw_not_supplied(self):
        """The eval's batch path calls this without `raw`; it scores against a
        curated expected set rather than needing the guard."""
        locs = parse_locations_text(self._payload(20))
        assert len(locs) == 20
