import json
import logging
import os
from datetime import datetime, timezone

import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session

from app.database import SessionLocal, purge_old_records
from app.models import Site, ClientCount

logger = logging.getLogger(__name__)

SITES_CONFIG = os.environ.get("SITES_CONFIG", "/app/config/sites.yaml")


def _load_config() -> dict:
    with open(SITES_CONFIG) as f:
        return yaml.safe_load(f)


def _get_collector(platform: str, site_id: str, config: dict):
    if platform == "mist":
        from app.collectors.mist import MistCollector
        return MistCollector(site_id, config)
    if platform == "cisco9800":
        from app.collectors.cisco9800 import Cisco9800Collector
        return Cisco9800Collector(site_id, config)
    if platform == "cisco9800cli":
        from app.collectors.cisco9800_cli import Cisco9800CliCollector
        return Cisco9800CliCollector(site_id, config)
    if platform == "cisco5500":
        from app.collectors.cisco5500 import Cisco5500Collector
        return Cisco5500Collector(site_id, config)
    if platform == "cisco5505":
        from app.collectors.cisco5505 import Cisco5505Collector
        return Cisco5505Collector(site_id, config)
    raise ValueError(f"Unknown platform: {platform}")


def poll_all_sites():
    logger.info("Starting poll cycle")
    try:
        cfg = _load_config()
    except Exception as exc:
        logger.error("Failed to load sites config: %s", exc)
        return

    ssids: list[str] = cfg.get("ssids", ["grainger", "wwg-net"])
    sites: list[dict] = cfg.get("sites", [])
    now = datetime.now(timezone.utc).isoformat()

    db: Session = SessionLocal()
    try:
        for site_cfg in sites:
            site_id = site_cfg["id"]
            platform = site_cfg["platform"]

            # Upsert site record
            site = db.get(Site, site_id)
            if site is None:
                site = Site(
                    id=site_id,
                    name=site_cfg.get("name", site_id),
                    platform=platform,
                    config_json=json.dumps(site_cfg),
                )
                db.add(site)
            else:
                site.name = site_cfg.get("name", site_id)
                site.platform = platform
                site.config_json = json.dumps(site_cfg)

            # Placeholder sites are registered (so they appear on the dashboard
            # as "pending") but never polled.
            if platform == "placeholder":
                logger.info("site %s is a placeholder; not polling", site_id)
                continue

            try:
                collector = _get_collector(platform, site_id, site_cfg)
                counts = collector.collect(ssids)
            except Exception as exc:
                logger.error("site %s collector error: %s", site_id, exc)
                counts = None

            # A failed poll returns None: skip writing so we keep the last good
            # data rather than recording misleading zeros.
            if counts is None:
                logger.warning("site %s poll failed; keeping previous data", site_id)
                continue

            for ssid, count in counts.items():
                db.add(ClientCount(
                    site_id=site_id,
                    ssid=ssid,
                    client_count=count,
                    polled_at=now,
                ))
            logger.info("site %s polled: %s", site_id, counts)

        db.commit()
    except Exception as exc:
        logger.error("DB write error during poll: %s", exc)
        db.rollback()
    finally:
        db.close()


def nightly_purge():
    deleted = purge_old_records(days=30)
    logger.info("Nightly purge removed %d records", deleted)


def start_scheduler() -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(poll_all_sites, "interval", minutes=15, id="poll_sites", next_run_time=datetime.now(timezone.utc))
    scheduler.add_job(nightly_purge, "cron", hour=3, minute=0, id="nightly_purge")
    scheduler.start()
    logger.info("Scheduler started (poll every 15 min)")
    return scheduler
