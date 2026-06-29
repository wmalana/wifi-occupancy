import os
import re
import time
import logging
from collections import Counter

import paramiko

from app.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# Client rows in `show client summary` start with a colon-separated MAC.
_MAC_RE = re.compile(r"^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}")


def parse_wlan_summary(output: str) -> dict[str, str]:
    """Map WLAN id -> SSID from AireOS `show wlan summary` output.

    The combined column is "WLAN Profile Name / SSID" (e.g. "grcorpwid /
    grainger"); we take the SSID half. Names may contain spaces, so we slice
    by the fixed column positions defined by the header.
    """
    lines = output.splitlines()
    header = next((ln for ln in lines if "WLAN Profile" in ln and "Status" in ln), None)
    if header is None:
        return {}
    profile_start = header.index("WLAN Profile")
    status_start = header.index("Status")

    mapping: dict[str, str] = {}
    for ln in lines:
        wlan_id = ln[:profile_start].strip()
        if not wlan_id.isdigit():
            continue
        field = ln[profile_start:status_start].strip()
        ssid = field.split(" / ", 1)[1].strip() if " / " in field else field
        if ssid:
            mapping[wlan_id] = ssid
    return mapping


def count_clients_by_wlan(output: str) -> dict[str, int]:
    """Count clients per WLAN id from AireOS `show client summary`.

    The WLAN id is a fixed-width column; we slice it by header position rather
    than splitting on whitespace, because the Protocol column contains spaces
    (e.g. "802.11n(2.4 GHz)").
    """
    lines = output.splitlines()
    header = next((ln for ln in lines if "MAC Address" in ln and "WLAN" in ln), None)
    if header is None:
        return {}
    wlan_start = header.index("WLAN")
    auth_start = header.index("Auth", wlan_start)

    counts: Counter[str] = Counter()
    for ln in lines:
        if _MAC_RE.match(ln):
            wlan_id = ln[wlan_start:auth_start].strip()
            if wlan_id.isdigit():
                counts[wlan_id] += 1
    return dict(counts)


def tally_ssids(wlan_map: dict[str, str], wlan_counts: dict[str, int],
                ssids: list[str]) -> dict[str, int]:
    """Combine the id->ssid map and per-id counts into per-SSID totals."""
    counts = {s: 0 for s in ssids}
    for wlan_id, n in wlan_counts.items():
        ssid = wlan_map.get(wlan_id)
        if ssid in counts:
            counts[ssid] += n
    return counts


def _read_until(shell, tokens, max_wait: float = 20.0, settle: float = 0.3) -> str:
    """Read until the output ends with one of `tokens`.

    Raises TimeoutError if no token is seen before max_wait, so a truncated
    read is treated as a failed poll (the scheduler then keeps the last good
    data) rather than silently producing under-counted output.
    """
    out = ""
    waited = 0.0
    while waited < max_wait:
        time.sleep(settle)
        waited += settle
        while shell.recv_ready():
            out += shell.recv(65535).decode("utf-8", errors="replace")
        if any(out.rstrip().endswith(t) for t in tokens):
            return out
    raise TimeoutError(f"timed out waiting for {tokens!r} after {max_wait}s ({len(out)} bytes read)")


def _login(shell, username: str, password: str) -> None:
    """AireOS prompts User:/Password: over the shell even after SSH auth."""
    out = _read_until(shell, ["User:", ">"], max_wait=10)
    if "User:" in out:
        shell.sendall(username + "\n")
        _read_until(shell, ["assword:"], max_wait=10)
        shell.sendall(password + "\n")
        _read_until(shell, [">"], max_wait=15)


def _run(shell, cmd: str, max_wait: float = 30.0) -> str:
    """Send a command and read until the AireOS prompt ("(name) >") returns."""
    shell.sendall(cmd + "\n")
    return _read_until(shell, [">"], max_wait=max_wait)


class Cisco5500Collector(BaseCollector):
    """Polls a Cisco 5500-series (AireOS) WLC over SSH for per-SSID counts.

    AireOS has a different CLI from the IOS-XE 9800: an interactive User:/
    Password: login, `config paging disable`, and `show wlan summary` /
    `show client summary` with their own column layouts.
    """

    def collect(self, ssids: list[str]) -> dict[str, int] | None:
        host = self.config.get("host", "")
        port = int(self.config.get("port", 22))
        username = os.environ.get(self.config.get("username_env", "CISCO_USER"), "")
        password = os.environ.get(self.config.get("password_env", "CISCO_PASS"), "")

        if not host or not username or not password:
            logger.error("site %s: missing host or credentials", self.site_id)
            return None

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            ssh.connect(
                hostname=host,
                port=port,
                username=username,
                password=password,
                timeout=20,
                look_for_keys=False,
                allow_agent=False,
            )

            shell = ssh.invoke_shell()
            shell.settimeout(20)  # never block the whole poll cycle
            _login(shell, username, password)
            _run(shell, "config paging disable", max_wait=10)

            wlan_map = parse_wlan_summary(_run(shell, "show wlan summary"))
            wlan_counts = count_clients_by_wlan(_run(shell, "show client summary"))
            return tally_ssids(wlan_map, wlan_counts, ssids)

        except Exception as exc:
            logger.error("site %s Cisco 5500 (AireOS) poll failed: %s", self.site_id, exc)
            return None
        finally:
            ssh.close()  # always release the session, even on failure
