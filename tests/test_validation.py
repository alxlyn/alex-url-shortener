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
    "https://[::1",                      # unclosed bracket, used to crash with a 500
    "https://x\u2100.com/",              # changes under Unicode normalization, also crashed
    "https://%65vil.com",                # percent-escape in the host
]

ACCEPTED = [
    ("example.com", "https://example.com"),
    ("https://example.com/path?q=1", "https://example.com/path?q=1"),
    ("http://sub.example.co.uk", "http://sub.example.co.uk"),
    ("example.com:8080/x", "https://example.com:8080/x"),
    ("example.com/?next=https://other.com", "https://example.com/?next=https://other.com"),
]


@pytest.mark.parametrize("raw", REJECTED)
def test_rejects(raw):
    assert normalize_url(raw) is None


@pytest.mark.parametrize("raw,expected", ACCEPTED)
def test_accepts(raw, expected):
    assert normalize_url(raw) == expected


@pytest.mark.parametrize("raw", [
    "https://sho.rt/abc123",
    "https://SHO.RT/abc123",
    "https://sho.rt./abc123",                         # trailing dot
    "https://\uff53\uff48\uff4f.\uff52\uff54/abc123",  # full-width letters
])
def test_rejects_links_to_the_shortener_itself(monkeypatch, raw):
    monkeypatch.setattr(app_module, "PUBLIC_BASE_URL", "https://sho.rt")
    assert normalize_url(raw) is None
