"""Unit tests for the Juniper Mist collector.

These tests never touch the real Mist API. Instead we *mock* httpx (the HTTP
client the collector uses) and hand it a fake list of connected clients, then
assert that the collector counts them correctly per SSID.
"""
from unittest.mock import MagicMock, patch

from app.collectors.mist import MistCollector

# The two WiFi networks the app tracks.
SSIDS = ["grainger", "wwg-net"]


def _fake_httpx_client(clients=None, raise_status=False):
    """Build a stand-in for httpx.Client that mimics how the collector uses it.

    The collector does:
        with httpx.Client(...) as client:
            resp = client.get(url, headers=...)
            resp.raise_for_status()
            clients = resp.json()

    So we return a fake factory whose context manager yields a fake `client`
    whose `.get()` returns a fake `resp`.
    """
    resp = MagicMock()
    resp.json.return_value = clients or []
    if raise_status:
        resp.raise_for_status.side_effect = Exception("simulated API error")

    client = MagicMock()
    client.get.return_value = resp

    cm = MagicMock()
    cm.__enter__.return_value = client       # `with ... as client`
    cm.__exit__.return_value = False

    return MagicMock(return_value=cm)         # httpx.Client(...) -> cm


def test_counts_clients_per_ssid(monkeypatch):
    """Happy path: count clients per tracked SSID, ignore everything else."""
    monkeypatch.setenv("MIST_API_TOKEN", "fake-token")
    clients = [
        {"ssid": "grainger"},
        {"ssid": "grainger"},
        {"ssid": "wwg-net"},
        {"ssid": "guest-wifi"},      # not tracked -> ignored
        {"mac": "aa:bb:cc"},         # no ssid key at all -> ignored
    ]
    collector = MistCollector("site-1", {"mist_site_id": "abc123"})

    with patch("app.collectors.mist.httpx.Client", _fake_httpx_client(clients)):
        counts = collector.collect(SSIDS)

    assert counts == {"grainger": 2, "wwg-net": 1}


def test_uses_correct_url_and_auth_header(monkeypatch):
    """The collector should hit /sites/<id>/stats/clients with a Token header."""
    monkeypatch.setenv("MIST_API_TOKEN", "fake-token")
    collector = MistCollector("site-1", {"mist_site_id": "abc123"})
    factory = _fake_httpx_client([])

    with patch("app.collectors.mist.httpx.Client", factory):
        collector.collect(SSIDS)

    fake_client = factory.return_value.__enter__.return_value
    url, kwargs = fake_client.get.call_args.args[0], fake_client.get.call_args.kwargs
    assert url.endswith("/sites/abc123/stats/clients")
    assert kwargs["headers"]["Authorization"] == "Token fake-token"


def test_missing_token_returns_zeros(monkeypatch):
    """No API token -> return zero counts, never call the API."""
    monkeypatch.delenv("MIST_API_TOKEN", raising=False)
    collector = MistCollector("site-1", {"mist_site_id": "abc123"})

    counts = collector.collect(SSIDS)

    assert counts == {"grainger": 0, "wwg-net": 0}


def test_missing_site_id_returns_zeros(monkeypatch):
    """No mist_site_id in config -> return zero counts."""
    monkeypatch.setenv("MIST_API_TOKEN", "fake-token")
    collector = MistCollector("site-1", {})  # no mist_site_id

    counts = collector.collect(SSIDS)

    assert counts == {"grainger": 0, "wwg-net": 0}


def test_api_error_returns_zeros(monkeypatch):
    """If the API call fails, the collector swallows it and returns zeros.

    The scheduler relies on this: one broken site must not break the poll.
    """
    monkeypatch.setenv("MIST_API_TOKEN", "fake-token")
    collector = MistCollector("site-1", {"mist_site_id": "abc123"})

    with patch("app.collectors.mist.httpx.Client", _fake_httpx_client(raise_status=True)):
        counts = collector.collect(SSIDS)

    assert counts == {"grainger": 0, "wwg-net": 0}
