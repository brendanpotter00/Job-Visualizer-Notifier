"""Unit tests for the one-time Haiku recipe generator."""

from __future__ import annotations

import pytest

from api.services import recipe_generator
from api.services.recipe_generator import (
    MissingAnthropicKeyError,
    RecipeGenerationError,
    parse_recipe_text,
)



VALID_RECIPE_JSON = (
    '{"endpoint": "https://careers.example.com/api/jobs", "method": "GET", '
    '"list_path": "data.jobs", "base_url": "https://careers.example.com", '
    '"body_template": null, '
    '"field_map": {"id": "id", "title": "title", "url": "url", '
    '"location": "loc", "posted_on": null}, '
    '"pagination": {"type": "offset", "param": "start", "page_size": 20, "start": 0}}'
)


class TestParseRecipeText:
    def test_valid(self):
        recipe = parse_recipe_text(VALID_RECIPE_JSON)
        assert recipe["endpoint"] == "https://careers.example.com/api/jobs"
        assert recipe["field_map"]["id"] == "id"
        assert recipe["pagination"]["type"] == "offset"

    def test_empty_raises(self):
        with pytest.raises(RecipeGenerationError):
            parse_recipe_text("")

    def test_non_json_raises(self):
        with pytest.raises(RecipeGenerationError):
            parse_recipe_text("not json at all")

    def test_missing_field_map_raises(self):
        with pytest.raises(RecipeGenerationError):
            parse_recipe_text('{"endpoint": "https://x.com", "list_path": "a"}')

    def test_relative_endpoint_rejected(self):
        bad = VALID_RECIPE_JSON.replace(
            "https://careers.example.com/api/jobs", "/api/jobs"
        )
        with pytest.raises(RecipeGenerationError):
            parse_recipe_text(bad)

    def test_bad_pagination_type_rejected(self):
        bad = VALID_RECIPE_JSON.replace('"type": "offset"', '"type": "cursor"')
        with pytest.raises(RecipeGenerationError):
            parse_recipe_text(bad)


@pytest.mark.asyncio
class TestGenerateRecipe:
    async def test_no_candidates_raises(self):
        with pytest.raises(RecipeGenerationError):
            await recipe_generator.generate_recipe("https://x.com", [])

    async def test_missing_api_key_degrades(self, monkeypatch):
        monkeypatch.setattr(
            recipe_generator.settings, "anthropic_api_key", "", raising=False
        )
        with pytest.raises(MissingAnthropicKeyError):
            await recipe_generator.generate_recipe(
                "https://x.com", [{"method": "GET", "url": "https://x.com/api", "sample": {"jobs": []}}]
            )

    async def test_generate_parses_model_output(self, monkeypatch):
        monkeypatch.setattr(
            recipe_generator.settings, "anthropic_api_key", "sk-test", raising=False
        )

        class _Block:
            type = "text"
            text = VALID_RECIPE_JSON

        class _Resp:
            content = [_Block()]

        class _Messages:
            async def create(self, **kwargs):
                # Assert we used the structured-output json_schema path.
                assert kwargs["output_config"]["format"]["type"] == "json_schema"
                return _Resp()

        class _Client:
            def __init__(self, *a, **k):
                self.messages = _Messages()

        monkeypatch.setattr(recipe_generator, "AsyncAnthropic", _Client)
        recipe = await recipe_generator.generate_recipe(
            "https://careers.example.com",
            [{"method": "GET", "url": "https://careers.example.com/api", "sample": {"data": {"jobs": []}}}],
        )
        assert recipe["endpoint"] == "https://careers.example.com/api/jobs"
