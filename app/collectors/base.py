from abc import ABC, abstractmethod


class BaseCollector(ABC):
    """Returns a dict mapping ssid -> client_count for a single site."""

    def __init__(self, site_id: str, config: dict):
        self.site_id = site_id
        self.config = config

    @abstractmethod
    def collect(self, ssids: list[str]) -> dict[str, int]:
        """Collect client counts for each SSID. Returns {ssid: count}."""
