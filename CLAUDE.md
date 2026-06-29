# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A FastAPI app that polls WiFi controllers every 15 minutes and shows per-site,
per-SSID client counts on a Chart.js dashboard. Built for facilities/occupancy
planning. Two SSIDs are tracked by default: `grainger` (corporate laptops) and
`wwg-net` (company-managed phones).

## Run / develop

```bash
cp .env.example .env          # fill in MIST_API_TOKEN, CISCO_USER, CISCO_PASS
# edit config/sites.yaml with real site IDs, hostnames, platform types
docker-compose up --build     # → http://localhost:8080
```

Run locally without Docker (override the container-default paths, which point at `/app`):

```bash
pip install -r requirements.txt
DB_PATH=./data/occupancy.db SITES_CONFIG=./config/sites.yaml \
  uvicorn app.main:app --reload --port 8080
```

Manually trigger a poll cycle (dev): `curl -X POST http://localhost:8080/api/poll`

There is **no test suite, linter, or CI** configured. Verify changes by running
the app and hitting `/api/poll` + the endpoints.

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
  A collector exception is swallowed and recorded as zero counts so one bad site
  never blocks the others.
- **`app/collectors/`** — one collector per controller type, all subclassing
  `BaseCollector` (`base.py`). Each implements `collect(ssids) -> {ssid: count}`
  and must **return zero counts on failure rather than raise** (the scheduler relies
  on this; collectors log the error and return `{s: 0 for s in ssids}`):
  - `mist.py` — Juniper Mist REST API via httpx; counts clients whose `ssid` matches.
  - `cisco9800.py` — Cisco Catalyst 9800 via NETCONF (ncclient, port 830); parses
    `ms-assoc-ssid` from `client-oper-data` YANG XML.
  - `cisco5505.py` — Cisco legacy 5505 via SSH (paramiko, interactive shell). Runs
    `show wireless client summary`, and falls back to `show dot11 associations` if
    that returns all zeros. Parsing is regex/string-count based and fragile.
- **`app/routers/`** — `sites.py` (`GET /api/sites`) and `counts.py`
  (`/api/counts/latest`, `/daily`, raw `/api/counts`). Read endpoints use **raw SQL
  via `text()`**, not the ORM; the "latest" query is a correlated-subquery
  max-per-group.
- **`app/database.py`** — single SQLite engine with `check_same_thread=False`
  (the scheduler thread and request threads share it). `purge_old_records()` is
  raw `DELETE`.
- **`app/models.py` / `app/schemas.py`** — SQLAlchemy 2.0 ORM models and Pydantic
  v2 response models.

## Conventions that matter

- **Timestamps are ISO-8601 UTC strings**, not datetime columns. `polled_at` is a
  `String`; the "latest" logic depends on lexicographic ordering of these strings
  matching chronological order, and `/daily` uses SQLite `DATE(...)`. Keep writing
  UTC ISO strings (`datetime.now(timezone.utc).isoformat()`).
- **Site config lives in `config/sites.yaml`, not the DB.** The `sites` table is a
  derived cache rebuilt on every poll from the YAML; `config_json` stores the raw
  per-site dict. To add/change a site, edit the YAML.
- **Credentials are referenced by env-var name.** Each site entry names
  `username_env` / `password_env` (default `CISCO_USER` / `CISCO_PASS`); collectors
  read `os.environ[...]` at poll time. Mist uses the single global `MIST_API_TOKEN`.
- **Adding a collector:** create `app/collectors/<platform>.py` subclassing
  `BaseCollector`, then register it in `scheduler._get_collector()` (the only
  dispatch point). Imports there are lazy/per-branch.
- **Paths default to `/app/...`** (the container layout). Override `DB_PATH` and
  `SITES_CONFIG` env vars when running outside Docker.

## Roadmap

`HANDOFF.md` lists planned-but-unbuilt features (capacity %, summary endpoint,
freshness indicator, heatmap, anomaly detection, CSV export, Slack/email digest)
in suggested implementation order, each with the backend + frontend touch points.
