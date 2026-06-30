# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI app that polls WiFi controllers every 15 minutes and shows per-site,
per-SSID client counts on a plain-HTML dashboard (summary cards + a site × date
peak-counts table). Built for facilities/occupancy planning. Two SSIDs are
tracked by default: `grainger` (corporate laptops) and `wwg-net`
(company-managed phones), but the SSID list is config-driven.

## Run / develop

```bash
cp .env.example .env          # MIST_API_TOKEN, MIST_API_BASE, CISCO_USER, CISCO_PASS
# edit config/sites.yaml with real site IDs, hostnames, platform types
docker-compose up --build     # → http://localhost:8080
```

Run locally without Docker. **Use Python 3.12** (matches the Dockerfile; 3.14 can't
build `pydantic-core` wheels). Override the container-default paths, which point at `/app`:

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
set -a; source .env; set +a            # the app reads env vars, it does not load .env itself
DB_PATH=./data/occupancy.db SITES_CONFIG=./config/sites.yaml \
  .venv/bin/uvicorn app.main:app --reload --port 8080
```

Manually trigger a poll cycle (dev): `curl -X POST http://localhost:8080/api/poll`

### Tests

`pytest` (in `requirements-dev.txt`). Run `.venv/bin/python -m pytest tests/ -v`
(use `python -m pytest` so `app` is importable). Collector parsing logic is split
into **pure functions** tested against sample command output — no device/network
needed. GitHub Actions (`.github/workflows/test.yml`) runs the suite on every push
and PR; `main` is branch-protected requiring that check.

## Architecture

Request/serve and background polling are two separate paths sharing one SQLite DB.

- **`app/main.py`** — builds the FastAPI app, starts the scheduler in the
  `lifespan` context, includes routers, and mounts `static/` at `/`. The static
  mount is registered **last** so `/api/*` routes win.
- **`app/scheduler.py`** — `poll_all_sites()` is the heart of the system. On each
  cycle it loads `sites.yaml`, upserts each `Site` row, dispatches to a collector
  by `platform`, and writes one `ClientCount` row per (site, ssid). `start_scheduler()`
  registers two APScheduler jobs: poll every 15 min (fires immediately on startup
  via `next_run_time`) and `nightly_purge` at 03:00 UTC (30-day retention).
  A collector returning `None` (failure) or a `placeholder`-platform site is
  **skipped without writing**, so one bad site never blocks the others and a failed
  poll keeps the last good data instead of recording misleading zeros.
- **`app/collectors/`** — one collector per controller type, all subclassing
  `BaseCollector` (`base.py`). Each implements `collect(ssids) -> {ssid: count} | None`
  and must **return `None` on failure (not raise, not zeros)**; the scheduler relies
  on this. A successful poll that genuinely finds no clients still returns a dict of zeros.
  - `mist.py` — Juniper Mist REST API via httpx. Host is `MIST_API_BASE`
    (default `https://api.mist.com`; set per region, e.g. `https://api.ac2.mist.com`).
  - `cisco9800.py` — Cisco Catalyst 9800 via **NETCONF** (ncclient, port 830);
    parses `ms-assoc-ssid` from `client-oper-data` YANG XML.
  - `cisco9800cli.py` — Cisco 9800 via the **SSH CLI** (port 22), for when NETCONF
    isn't reachable. Maps WLAN id → SSID via `show wlan summary`, counts clients per
    WLAN id via `show wireless client summary`.
  - `cisco5500.py` — Cisco 5500-series **AireOS** WLC via SSH. Interactive
    `User:`/`Password:` login, `config paging disable`, then `show wlan summary`
    (combined "Profile / SSID" column) + `show client summary` (WLAN id is a
    fixed-width column).
  - `cisco5505.py` — legacy Cisco 5505 via SSH (`show wireless client summary`,
    fallback `show dot11 associations`).
  - SSH collectors parse fixed-width tables **by header column position** (names can
    contain spaces) and read until the device prompt; reads that time out raise so a
    truncated poll fails cleanly rather than under-counting.
- **`app/routers/`** — `sites.py` (`GET /api/sites`, includes `platform`) and
  `counts.py` (`/api/counts/latest`, `/daily`, raw `/api/counts`). Read endpoints use
  **raw SQL via `text()`**, not the ORM; "latest" is a correlated-subquery
  max-per-group; `/daily` returns the last N days (inclusive of today).
- **`app/database.py`** — single SQLite engine with `check_same_thread=False`
  (the scheduler thread and request threads share it). `purge_old_records()` is raw `DELETE`.
- **`app/static/`** — plain HTML/CSS/JS dashboard (no build step, no framework).
  `app.js` renders summary cards (with a data-freshness dot) and the site × date
  table from `/api/sites` + `/api/counts/daily`. SSIDs and dates are derived from the
  data; dates use **UTC** to match the backend's `DATE(polled_at)` aggregation.

## Conventions that matter

- **Collector failure contract:** return `None` to signal a failed poll → scheduler
  skips writing. Returning zeros would look like an empty site and pollute the
  daily/peak history. Genuine "zero clients" still returns a dict.
- **Timestamps are ISO-8601 UTC strings**, not datetime columns. `polled_at` is a
  `String`; "latest" depends on lexicographic ordering matching chronological order,
  and `/daily` uses SQLite UTC `DATE(...)`. Keep writing `datetime.now(timezone.utc).isoformat()`.
  Frontend date math must use UTC (`getUTCDate`, etc.) to line up with the data.
- **Site config lives in `config/sites.yaml`, not the DB.** The `sites` table is a
  derived cache rebuilt on every poll from the YAML (upsert only — removed sites are
  **not** purged). `config_json` stores the raw per-site dict. To add/change a site,
  edit the YAML.
- **`platform: placeholder`** registers a site (so it appears on the dashboard as a
  pending card / empty table row) but is never polled.
- **Credentials are referenced by env-var name.** Each site entry names
  `username_env` / `password_env` (default `CISCO_USER` / `CISCO_PASS`); collectors
  read `os.environ[...]` at poll time. Mist uses the global `MIST_API_TOKEN`.
- **Adding a collector:** create `app/collectors/<platform>.py` subclassing
  `BaseCollector` (return `None` on failure), put parsing in pure module-level
  functions with unit tests, then register it in `scheduler._get_collector()` (the
  only dispatch point; imports there are lazy/per-branch).
- **Paths default to `/app/...`** (container layout). Override `DB_PATH` and
  `SITES_CONFIG` env vars when running outside Docker.

## Roadmap

`HANDOFF.md` lists the original planned features. Done since: data-freshness dot,
plus the CLI/AireOS collectors, regional Mist support, placeholder sites, and the
peak-counts table. Still open: capacity %, summary endpoint, peak-hours heatmap,
anomaly detection, CSV export, Slack/email digest. Two known follow-ups: purge
orphaned sites removed from config, and bring `cisco9800cli`'s read loop in line
with `cisco5500`'s raise-on-timeout.
