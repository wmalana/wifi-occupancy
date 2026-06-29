import os
import re
import time
import logging
from collections import Counter

import paramiko

from app.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# `show wireless client summary` rows carry the WLAN id as "WLAN <n>":
#   0041.0e48.fc6f C100A-FL01-06-AP-6   WLAN 1    Run   11ax(5)  Dot1x  Local
_CLIENT_WLAN_RE = re.compile(r"\bWLAN\s+(\d+)\b")


def parse_wlan_summary(output: str) -> dict[str, str]:
    """Map WLAN id -> SSID from `show wlan summary` output.

    Cisco WLAN profile names and SSIDs are free-form and may contain spaces
    (e.g. "Corp WiFi"), so we slice by the fixed column positions defined by
    the header row rather than splitting on whitespace.
    """
    lines = output.splitlines()
    header = next((ln for ln in lines if "Profile Name" in ln and "SSID" in ln), None)
    if header is None:
        return {}
    id_end = header.index("Profile Name")
    ssid_start = header.index("SSID")
    status_start = header.find("Status", ssid_start)

    mapping: dict[str, str] = {}
    for ln in lines:
        wlan_id = ln[:id_end].strip()
        if not wlan_id.isdigit():
            continue
        ssid = (ln[ssid_start:status_start] if status_start != -1 else ln[ssid_start:]).strip()
        if ssid:
            mapping[wlan_id] = ssid
    return mapping


def count_clients_by_wlan(output: str) -> dict[str, int]:
    """Count client rows per WLAN id from `show wireless client summary`."""
    counts: Counter[str] = Counter()
    for line in output.splitlines():
        m = _CLIENT_WLAN_RE.search(line)
        if m:
            counts[m.group(1)] += 1
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


def _run(shell, cmd: str, settle: float = 0.3, max_wait: float = 30.0) -> str:
    """Send a command and read until the device prompt returns.

    Waiting for the trailing prompt (rather than stopping at the first idle
    gap) avoids truncating large tables that the controller emits in multiple
    bursts on a busy box.
    """
    shell.sendall(cmd + "\n")
    out = ""
    waited = 0.0
    while waited < max_wait:
        time.sleep(settle)
        waited += settle
        while shell.recv_ready():
            out += shell.recv(65535).decode("utf-8", errors="replace")
        if out.rstrip().endswith(("#", ">")):  # CLI prompt = command done
            break
    return out


class Cisco9800CliCollector(BaseCollector):
    """Polls a Cisco Catalyst 9800 over the SSH CLI (port 22) for per-SSID counts.

    Use this instead of the NETCONF collector when NETCONF (port 830) is not
    reachable. It maps WLAN id -> SSID via `show wlan summary`, then counts
    clients per WLAN id via `show wireless client summary`.
    """

    def collect(self, ssids: list[str]) -> dict[str, int]:
        host = self.config.get("host", "")
        port = int(self.config.get("port", 22))
        username = os.environ.get(self.config.get("username_env", "CISCO_USER"), "")
        password = os.environ.get(self.config.get("password_env", "CISCO_PASS"), "")

        if not host or not username or not password:
            logger.error("site %s: missing host or credentials", self.site_id)
            return None

        counts = {s: 0 for s in ssids}

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
            shell.settimeout(20)  # never let a recv block the whole poll cycle
            time.sleep(1)
            while shell.recv_ready():  # drain login banner without blocking
                shell.recv(65535)
            _run(shell, "terminal length 0", settle=0.5, max_wait=5)

            wlan_map = parse_wlan_summary(_run(shell, "show wlan summary"))
            wlan_counts = count_clients_by_wlan(_run(shell, "show wireless client summary"))
            counts = tally_ssids(wlan_map, wlan_counts, ssids)

        except Exception as exc:
            logger.error("site %s Cisco 9800 CLI poll failed: %s", self.site_id, exc)
            return None
        finally:
            ssh.close()  # always release the session, even on failure

        return counts
