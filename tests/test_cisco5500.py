"""Unit tests for the Cisco 5500 (AireOS) collector's parsing logic.

Pure functions tested against column-aligned samples of real AireOS output.
"""
import pytest

from app.collectors.cisco5500 import (
    parse_wlan_summary,
    count_clients_by_wlan,
    tally_ssids,
    _read_until,
    Cisco5500Collector,
)

SSIDS = ["grainger", "wwg-net"]

# `show wlan summary` — combined "WLAN Profile Name / SSID" column. Built with
# fixed widths so header and rows align; includes an SSID with a space.
_W = "{:<9}{:<73}{:<10}{:<22}{}"
WLAN_SUMMARY = "\n".join([
    "show wlan summary",
    "",
    "Number of WLANs.................................. 4",
    "",
    _W.format("WLAN ID", "WLAN Profile Name / SSID", "Status", "Interface Name", "PMIPv6 Mobility"),
    "-" * 130,
    _W.format("1", "grcorpwid / grcorpwid", "Enabled", "vlan197", "none"),
    _W.format("17", "wwg-guest / wwg-guest", "Enabled", "management", "none"),
    _W.format("34", "grainger / grainger", "Enabled", "vlan197", "none"),
    _W.format("40", "Corp Net / Corp WiFi", "Enabled", "vlan198", "none"),
    "",
    "(jvlwlc1) >",
])

# `show client summary` — WLAN id is a fixed-width column; Protocol has a space.
_C = "{:<18}{:<31}{:<5}{:<14}{:<6}{:<5}{:<22}{}"
CLIENT_SUMMARY = "\n".join([
    "show client summary",
    "",
    "Number of Clients................................ 4",
    "",
    _C.format("MAC Address", "AP Name", "Slot", "Status", "WLAN", "Auth", "Protocol", "Role"),
    "-" * 120,
    _C.format("10:b1:df:9e:42:9f", "jvlwap001", "0", "Associated", "34", "Yes", "802.11n(2.4 GHz)", "Local"),
    _C.format("aa:bb:cc:dd:ee:01", "jvlwap002", "0", "Associated", "34", "Yes", "802.11ac(5 GHz)", "Local"),
    _C.format("18:fe:34:71:76:6b", "jvlwap102", "0", "Associated", "17", "Yes", "802.11n(2.4 GHz)", "Local"),
    _C.format("02:d3:34:f9:22:47", "jvlwap098", "0", "Associated", "2", "Yes", "802.11n(2.4 GHz)", "Local"),
    "",
    "(jvlwlc1) >",
])


def test_parse_wlan_summary():
    mapping = parse_wlan_summary(WLAN_SUMMARY)
    assert mapping["34"] == "grainger"
    assert mapping["1"] == "grcorpwid"
    assert mapping["17"] == "wwg-guest"
    assert len(mapping) == 4
    assert "WLAN" not in mapping  # header line not parsed


def test_parse_wlan_summary_handles_spaces():
    """The SSID half of "Corp Net / Corp WiFi" must be captured whole."""
    assert parse_wlan_summary(WLAN_SUMMARY)["40"] == "Corp WiFi"


def test_count_clients_by_wlan():
    # Protocol column contains spaces — must not throw off the WLAN slice.
    assert count_clients_by_wlan(CLIENT_SUMMARY) == {"34": 2, "17": 1, "2": 1}


def test_tally_genuine_zero_for_absent_ssid():
    """grainger is on WLAN 34 (2 clients); wwg-net isn't broadcast -> 0."""
    wlan_map = parse_wlan_summary(WLAN_SUMMARY)
    wlan_counts = count_clients_by_wlan(CLIENT_SUMMARY)
    assert tally_ssids(wlan_map, wlan_counts, SSIDS) == {"grainger": 2, "wwg-net": 0}


class _FakeShell:
    """Yields its chunks once, then never produces a prompt."""
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def recv_ready(self):
        return bool(self._chunks)

    def recv(self, _n):
        return self._chunks.pop(0)


def test_read_until_raises_on_timeout():
    """No trailing prompt before max_wait -> TimeoutError (a failed poll)."""
    shell = _FakeShell([b"partial output with no prompt\n"])
    with pytest.raises(TimeoutError):
        _read_until(shell, [">"], max_wait=0.5, settle=0.1)


def test_collect_missing_credentials_returns_none(monkeypatch):
    monkeypatch.delenv("CISCO_USER", raising=False)
    monkeypatch.delenv("CISCO_PASS", raising=False)
    collector = Cisco5500Collector("site-1", {"host": "10.20.211.11"})
    assert collector.collect(SSIDS) is None
