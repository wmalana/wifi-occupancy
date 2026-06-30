from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.schemas import LatestCountOut, DailyCountOut, ClientCountOut

router = APIRouter(prefix="/api/counts", tags=["counts"])


@router.get("/latest", response_model=list[LatestCountOut])
def latest_counts(db: Session = Depends(get_db)):
    """Return the most recent poll result per site per SSID."""
    rows = db.execute(text("""
        SELECT cc.site_id, s.name AS site_name, cc.ssid, cc.client_count, cc.polled_at
        FROM client_counts cc
        JOIN sites s ON s.id = cc.site_id
        WHERE cc.polled_at = (
            SELECT MAX(cc2.polled_at)
            FROM client_counts cc2
            WHERE cc2.site_id = cc.site_id AND cc2.ssid = cc.ssid
        )
        ORDER BY s.name, cc.ssid
    """)).fetchall()
    return [
        LatestCountOut(
            site_id=r.site_id,
            site_name=r.site_name,
            ssid=r.ssid,
            client_count=r.client_count,
            polled_at=r.polled_at,
        )
        for r in rows
    ]


@router.get("/daily", response_model=list[DailyCountOut])
def daily_counts(
    days: int = Query(30, ge=1, le=90),
    site_id: str = Query(None),
    db: Session = Depends(get_db),
):
    """Return daily aggregates (max and avg) per site per SSID for the past N days."""
    # Last N days *including today* → floor at today-(N-1), so a 7-day window
    # returns exactly 7 dates (not 8) and matches the dashboard's N columns.
    filters = "WHERE DATE(cc.polled_at) >= DATE('now', :offset)"
    params: dict = {"offset": f"-{days - 1} days"}
    if site_id:
        filters += " AND cc.site_id = :site_id"
        params["site_id"] = site_id

    rows = db.execute(text(f"""
        SELECT cc.site_id, s.name AS site_name, cc.ssid,
               DATE(cc.polled_at) AS date,
               MAX(cc.client_count) AS max_count,
               AVG(cc.client_count) AS avg_count
        FROM client_counts cc
        JOIN sites s ON s.id = cc.site_id
        {filters}
        GROUP BY cc.site_id, cc.ssid, DATE(cc.polled_at)
        ORDER BY cc.site_id, cc.ssid, date
    """), params).fetchall()

    return [
        DailyCountOut(
            site_id=r.site_id,
            site_name=r.site_name,
            ssid=r.ssid,
            date=r.date,
            max_count=r.max_count,
            avg_count=round(r.avg_count, 1),
        )
        for r in rows
    ]


@router.get("", response_model=list[ClientCountOut])
def raw_counts(
    site_id: str = Query(None),
    ssid: str = Query(None),
    from_ts: str = Query(None, alias="from"),
    to_ts: str = Query(None, alias="to"),
    limit: int = Query(500, ge=1, le=5000),
    db: Session = Depends(get_db),
):
    """Return raw poll records with optional filters."""
    conditions = []
    params: dict = {}
    if site_id:
        conditions.append("site_id = :site_id")
        params["site_id"] = site_id
    if ssid:
        conditions.append("ssid = :ssid")
        params["ssid"] = ssid
    if from_ts:
        conditions.append("polled_at >= :from_ts")
        params["from_ts"] = from_ts
    if to_ts:
        conditions.append("polled_at <= :to_ts")
        params["to_ts"] = to_ts

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params["limit"] = limit

    rows = db.execute(text(f"""
        SELECT id, site_id, ssid, client_count, polled_at
        FROM client_counts {where}
        ORDER BY polled_at DESC
        LIMIT :limit
    """), params).fetchall()

    return [
        ClientCountOut(
            id=r.id,
            site_id=r.site_id,
            ssid=r.ssid,
            client_count=r.client_count,
            polled_at=r.polled_at,
        )
        for r in rows
    ]
