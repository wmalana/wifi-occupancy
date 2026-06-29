import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import init_db
from app.scheduler import start_scheduler, poll_all_sites
from app.routers import sites, counts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="WiFi Occupancy Tracker", lifespan=lifespan)

app.include_router(sites.router)
app.include_router(counts.router)


# Dev-only: manual poll trigger
@app.post("/api/poll", tags=["dev"])
def trigger_poll():
    poll_all_sites()
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
