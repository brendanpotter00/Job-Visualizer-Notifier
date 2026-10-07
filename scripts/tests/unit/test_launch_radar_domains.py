"""Domain normalization: the shared vectors (CONTRACT §3) and the filters."""

import pytest

from launch_radar.domains import is_big_tech, is_hostname, normalize_domain


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("HTTPS://WWW.Raindrop.AI/blog/series-a/", "raindrop.ai"),
        ("athennian.com", "athennian.com"),
        ("ghost.ai:443", "ghost.ai"),
        ("user@www.Example.com/x?y#z", "example.com"),
        ("NA", None),
        ("localhost", None),
    ],
)
def test_contract_vectors(raw, expected):
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "   ", "n/a", "None", "null", "unknown", 42, ["a.com"]])
def test_nullish_and_non_strings(raw):
    assert normalize_domain(raw) is None


def test_trailing_dot_and_query():
    assert normalize_domain("https://foo.dev./?utm=1") == "foo.dev"
    assert normalize_domain("foo.dev#team") == "foo.dev"


def test_is_hostname_rejects_odd_values():
    assert is_hostname("raindrop.ai")
    assert is_hostname("sub.example.co.uk")
    assert not is_hostname("foo bar.com")
    assert not is_hostname("..evil.com")
    assert not is_hostname("evil_.com")


def test_big_tech_and_subdomains():
    assert is_big_tech("openai.com")
    assert is_big_tech("research.google.com")
    assert not is_big_tech("notgoogle.com")
    assert not is_big_tech("raindrop.ai")
