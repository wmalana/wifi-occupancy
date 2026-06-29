from abc import ABC, abstractmethod


class BaseCollector(ABC):
    """Returns a dict mapping ssid -> client_count for a single site."""

    def __init__(self, site_id: str, config: dict):
        self.site_id = site_id
        self.config = config

    @abstractmethod
    def collect(self, ssids: list[str]) -> dict[str, int] | None:
        """Collect client counts for each SSID.

        Returns {ssid: count} on success. Returns None to signal the poll
        failed (bad credentials, network error, etc.) so the scheduler can
        skip writing rather than record misleading zero counts. A successful
        poll that genuinely finds no clients still returns a dict of zeros.
        """
