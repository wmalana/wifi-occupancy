import os
import logging
import httpx
from app.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

MIST_BASE = "https://api.mist.com/api/v1"


class MistCollector(BaseCollector):
    """Polls Juniper Mist REST API for client counts per SSID."""

    def collect(self, ssids: list[str]) -> dict[str, int]:
        token = os.environ.get("MIST_API_TOKEN", "")
        site_id = self.config.get("mist_site_id", "")
        if not token or not site_id:
            logger.error("site %s: missing MIST_API_TOKEN or mist_site_id", self.site_id)
            return {s: 0 for s in ssids}

        headers = {"Authorization": f"Token {token}"}
        counts = {s: 0 for s in ssids}

        try:
            # Fetch all connected clients for the site
            url = f"{MIST_BASE}/sites/{site_id}/stats/clients"
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

        return counts
