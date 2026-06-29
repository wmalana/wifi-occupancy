"""Tests for the poll loop's skip-on-failure behavior.

Uses an in-memory SQLite DB (shared via StaticPool) and fake collectors, so no
network or real device is involved.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.scheduler as sched
from app.models import Base, ClientCount


def _setup(monkeypatch, sites, collectors):
    """Wire the scheduler to an in-memory DB and fake collectors."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine)

    monkeypatch.setattr(sched, "SessionLocal", TestSession)
    monkeypatch.setattr(sched, "_load_config", lambda: {
        "ssids": ["grainger", "wwg-net"],
        "sites": sites,
    })
    monkeypatch.setattr(sched, "_get_collector",
                        lambda platform, site_id, cfg: collectors[site_id])
    return TestSession


class _FakeCollector:
    def __init__(self, result):
        self._result = result

    def collect(self, ssids):
        return self._result


def test_failed_poll_writes_nothing(monkeypatch):
    """A site whose collector returns None must not get any count rows."""
    sites = [
        {"id": "ok", "platform": "x", "name": "OK Site"},
        {"id": "bad", "platform": "x", "name": "Bad Site"},
    ]
    collectors = {
        "ok": _FakeCollector({"grainger": 5, "wwg-net": 3}),
        "bad": _FakeCollector(None),  # poll failed
    }
    Session = _setup(monkeypatch, sites, collectors)

    sched.poll_all_sites()

    db = Session()
    by_site: dict[str, list] = {}
    for r in db.query(ClientCount).all():
        by_site.setdefault(r.site_id, []).append((r.ssid, r.client_count))
    db.close()

    assert "bad" not in by_site  # failed poll wrote nothing
    assert sorted(by_site["ok"]) == [("grainger", 5), ("wwg-net", 3)]


def test_genuine_zero_counts_are_written(monkeypatch):
    """A successful poll that finds zero clients still records zeros."""
    sites = [{"id": "empty", "platform": "x", "name": "Empty Site"}]
    collectors = {"empty": _FakeCollector({"grainger": 0, "wwg-net": 0})}
    Session = _setup(monkeypatch, sites, collectors)

    sched.poll_all_sites()

    db = Session()
    rows = db.query(ClientCount).filter_by(site_id="empty").all()
    db.close()

    assert {(r.ssid, r.client_count) for r in rows} == {("grainger", 0), ("wwg-net", 0)}
