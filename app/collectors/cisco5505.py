import os
import re
import logging
import paramiko
from app.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# Matches lines like: "  grainger              45"  or "  wwg-net               12"
_SUMMARY_RE = re.compile(r"^\s*(\S+)\s+(\d+)\s*$")


def _parse_wireless_client_summary(output: str, ssids: list[str]) -> dict[str, int]:
    """
    Parse 'show wireless client summary' output.
    The command prints a table; we look for SSID names in the first column.
    """
    counts = {s: 0 for s in ssids}
    for line in output.splitlines():
        m = _SUMMARY_RE.match(line)
        if m:
            name, count = m.group(1), int(m.group(2))
            if name in counts:
                counts[name] = count
    return counts


def _run_command(shell, cmd: str, timeout: int = 15) -> str:
    shell.sendall(cmd + "\n")
    import time
    time.sleep(timeout * 0.1)
    output = ""
    while shell.recv_ready():
        output += shell.recv(65535).decode("utf-8", errors="replace")
    return output


class Cisco5505Collector(BaseCollector):
    """Polls Cisco legacy 5505 via SSH for client counts per SSID."""

    def collect(self, ssids: list[str]) -> dict[str, int]:
        host = self.config.get("host", "")
        port = int(self.config.get("port", 22))
        username = os.environ.get(self.config.get("username_env", "CISCO_USER"), "")
        password = os.environ.get(self.config.get("password_env", "CISCO_PASS"), "")

        if not host or not username or not password:
            logger.error("site %s: missing host or credentials", self.site_id)
            return None

        counts = {s: 0 for s in ssids}

        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
            import time; time.sleep(1)
            shell.recv(65535)  # drain banner

            # Primary: show wireless client summary
            output = _run_command(shell, "show wireless client summary")
            counts = _parse_wireless_client_summary(output, ssids)

            # Fallback: if all zeros, try show dot11 associations
            if all(v == 0 for v in counts.values()):
                logger.debug("site %s: primary command returned zeros, trying fallback", self.site_id)
                output2 = _run_command(shell, "show dot11 associations")
                for ssid in ssids:
                    counts[ssid] = output2.count(ssid)

            ssh.close()

        except Exception as exc:
            logger.error("site %s Cisco 5505 SSH poll failed: %s", self.site_id, exc)
            return None

        return counts
