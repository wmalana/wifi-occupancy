import os
import logging
from xml.etree import ElementTree as ET
from app.collectors.base import BaseCollector

logger = logging.getLogger(__name__)

# Cisco-IOS-XE-wireless-client-oper YANG namespace
WIRELESS_CLIENT_NS = "http://cisco.com/ns/yang/Cisco-IOS-XE-wireless-client-oper"

CLIENT_FILTER = """
<filter xmlns="urn:ietf:params:xml:ns:netconf:base:1.0" type="subtree">
  <client-oper-data xmlns="http://cisco.com/ns/yang/Cisco-IOS-XE-wireless-client-oper">
    <common-oper-data>
      <client-mac/>
      <ms-assoc-ssid/>
    </common-oper-data>
  </client-oper-data>
</filter>
"""


class Cisco9800Collector(BaseCollector):
    """Polls Cisco Catalyst 9800 via NETCONF for client counts per SSID."""

    def collect(self, ssids: list[str]) -> dict[str, int]:
        try:
            from ncclient import manager as nc_manager
        except ImportError:
            logger.error("ncclient not installed")
            return {s: 0 for s in ssids}

        host = self.config.get("host", "")
        port = int(self.config.get("port", 830))
        username = os.environ.get(self.config.get("username_env", "CISCO_USER"), "")
        password = os.environ.get(self.config.get("password_env", "CISCO_PASS"), "")

        if not host or not username or not password:
            logger.error("site %s: missing host or credentials", self.site_id)
            return {s: 0 for s in ssids}

        counts = {s: 0 for s in ssids}

        try:
            with nc_manager.connect(
                host=host,
                port=port,
                username=username,
                password=password,
                hostkey_verify=False,
                timeout=30,
                device_params={"name": "iosxe"},
            ) as m:
                reply = m.get(filter=("subtree", CLIENT_FILTER))
                xml_data = str(reply)

            root = ET.fromstring(xml_data)
            ns = {"wc": WIRELESS_CLIENT_NS}

            for entry in root.iter(f"{{{WIRELESS_CLIENT_NS}}}common-oper-data"):
                ssid_el = entry.find("wc:ms-assoc-ssid", ns)
                if ssid_el is not None and ssid_el.text in counts:
                    counts[ssid_el.text] += 1

        except Exception as exc:
            logger.error("site %s Cisco 9800 NETCONF poll failed: %s", self.site_id, exc)

        return counts
