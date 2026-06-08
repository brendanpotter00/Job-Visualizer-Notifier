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
