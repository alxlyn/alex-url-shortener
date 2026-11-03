import pytest

import app as app_module
from app import normalize_url

REJECTED = [
    "https://",                          # no host
    "not a url at all",                  # spaces, no dot
    "ftp://example.com",                 # only http and https
    "vbscript:msgbox(1)",
    "mailto:someone@example.com",
    "//evil.com",                        # scheme-relative
    "https://paypal.com@evil.com",       # user info hides the real host
    "https://example.com/" + "a" * 2100, # too long
    "https://exa\nmple.com",             # control character
    "https://example.com:99999",         # invalid port
]

ACCEPTED = [
    ("example.com", "https://example.com"),
    ("https://example.com/path?q=1", "https://example.com/path?q=1"),
    ("http://sub.example.co.uk", "http://sub.example.co.uk"),
    ("example.com:8080/x", "https://example.com:8080/x"),
]


@pytest.mark.parametrize("raw", REJECTED)
def test_rejects(raw):
    assert normalize_url(raw) is None


@pytest.mark.parametrize("raw,expected", ACCEPTED)
def test_accepts(raw, expected):
    assert normalize_url(raw) == expected


def test_rejects_links_to_the_shortener_itself(monkeypatch):
    monkeypatch.setattr(app_module, "PUBLIC_BASE_URL", "https://sho.rt")
    assert normalize_url("https://sho.rt/abc123") is None
