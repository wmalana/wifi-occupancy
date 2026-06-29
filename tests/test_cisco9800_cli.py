"""Unit tests for the Cisco 9800 CLI collector's parsing logic.

The parsing functions are pure (string in, data out), so we test them against
realistic samples of the actual `show` command output — no device needed.
"""
from app.collectors.cisco9800_cli import (
    parse_wlan_summary,
    count_clients_by_wlan,
    tally_ssids,
    Cisco9800CliCollector,
)

SSIDS = ["grainger", "wwg-net"]

# `show wlan summary` is a fixed-column table. Build it with the same column
# widths the parser keys off of, so header and rows stay aligned — and include
# an SSID with a space to exercise the column-based (not whitespace) parsing.
_COL = "{:<5}{:<33}{:<33}{:<7}{}"
WLAN_SUMMARY = "\n".join([
    "show wlan summary",
    "",
    "Number of WLANs: 5",
    "",
    _COL.format("ID", "Profile Name", "SSID", "Status", "2.4GHz/5GHz Security"),
    "-" * 100,
    _COL.format("1", "grainger", "grainger", "UP", "[WPA2 + WPA3][802.1x]"),
    _COL.format("7", "wwg-guest", "wwg-guest", "UP", "[open],MAC Filtering"),
    _COL.format("10", "wwg-net", "wwg-net", "UP", "[WPA2 + WPA3][802.1x]"),
    _COL.format("42", "Corp Profile", "Corp WiFi", "UP", "[WPA2][802.1x]"),
    _COL.format("69", "rf-enroll", "rf-enroll", "UP", "[WPA2][PSK][AES]"),
    "",
    "C100-9800-WLC#",
])

# Trimmed sample of real `show wireless client summary` output.
CLIENT_SUMMARY = """show wireless client summary
Number of Clients: 6

MAC Address    AP Name                Type ID   State   Protocol Method  Role
-----------------------------------------------------------------------------------
0041.0e48.fc6f C100A-FL01-06-AP-6     WLAN 1    Run     11ax(5)  Dot1x   Local
0041.0e50.aabf C100A-FL02-14-AP-4     WLAN 1    Run     11ax(5)  Dot1x   Local
008a.76d4.1598 C100B-FL01-07-AP-2     WLAN 10   Run     11ax(5)  Dot1x   Export Foreign
02b3.d627.8dd4 C100B-FL03-23-AP-5     WLAN 10   Run     11ax(5)  Dot1x   Export Foreign
abcd.1234.5678 C100B-FL02-17-AP-9     WLAN 10   Run     11ax(5)  Dot1x   Local
04c2.9b05.324e C100B-FL02-17-AP-4     WLAN 7    Run     11n(2.4) MAB     Export Foreign

C100-9800-WLC#"""


def test_parse_wlan_summary():
    mapping = parse_wlan_summary(WLAN_SUMMARY)
    assert mapping["1"] == "grainger"
    assert mapping["10"] == "wwg-net"
    assert mapping["7"] == "wwg-guest"
    # Header / separator / prompt lines must not be parsed as WLANs.
    assert "ID" not in mapping
    assert len(mapping) == 5


def test_parse_wlan_summary_handles_spaces_in_names():
    """An SSID containing a space must be captured whole (column-based parse)."""
    mapping = parse_wlan_summary(WLAN_SUMMARY)
    assert mapping["42"] == "Corp WiFi"


def test_parse_wlan_summary_no_header_returns_empty():
    assert parse_wlan_summary("garbage\nno table here") == {}


def test_count_clients_by_wlan():
    counts = count_clients_by_wlan(CLIENT_SUMMARY)
    assert counts == {"1": 2, "10": 3, "7": 1}


def test_tally_ssids_maps_and_filters():
    wlan_map = parse_wlan_summary(WLAN_SUMMARY)
    wlan_counts = count_clients_by_wlan(CLIENT_SUMMARY)
    # grainger=WLAN1 (2), wwg-net=WLAN10 (3); wwg-guest (WLAN7) is ignored.
    assert tally_ssids(wlan_map, wlan_counts, SSIDS) == {"grainger": 2, "wwg-net": 3}


def test_tally_ignores_unknown_wlan_ids():
    # A WLAN id with no mapping (e.g. transient "WLAN 0") must be skipped, not crash.
    assert tally_ssids({"1": "grainger"}, {"1": 4, "0": 1}, SSIDS) == {"grainger": 4, "wwg-net": 0}


def test_collect_missing_credentials_returns_none(monkeypatch):
    monkeypatch.delenv("CISCO_USER", raising=False)
    monkeypatch.delenv("CISCO_PASS", raising=False)
    collector = Cisco9800CliCollector("site-1", {"host": "10.0.0.1"})
    assert collector.collect(SSIDS) is None
