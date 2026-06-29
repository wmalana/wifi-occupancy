import os
import logging
import httpx
from app.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# Mist has region-specific API hosts (api.mist.com, api.eu.mist.com,
# api.ac2.mist.com, ...). Override per deployment with the MIST_API_BASE env var.
DEFAULT_MIST_BASE = "https://api.mist.com"


class MistCollector(BaseCollector):
    """Polls Juniper Mist REST API for client counts per SSID."""

    def collect(self, ssids: list[str]) -> dict[str, int]:
        token = os.environ.get("MIST_API_TOKEN", "")
        site_id = self.config.get("mist_site_id", "")
        if not token or not site_id:
            logger.error("site %s: missing MIST_API_TOKEN or mist_site_id", self.site_id)
            return None

        # Accept either a host root ("https://api.ac2.mist.com") or a full base
        # that already includes the API path ("https://api.ac2.mist.com/api/v1").
        base = os.environ.get("MIST_API_BASE", DEFAULT_MIST_BASE).rstrip("/")
        if base.endswith("/api/v1"):
            base = base[: -len("/api/v1")]
        headers = {"Authorization": f"Token {token}"}
        counts = {s: 0 for s in ssids}

        try:
            # Fetch all connected clients for the site
            url = f"{base}/api/v1/sites/{site_id}/stats/clients"
            with httpx.Client(timeout=30) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                clients = resp.json()

            for c in clients:
                ssid = c.get("ssid", "")
                if ssid in counts:
                    counts[ssid] += 1

        except Exception as exc:
            logger.error("site %s Mist poll failed: %s", self.site_id, exc)
            return None

        return counts
