from pydantic import BaseModel


class SiteOut(BaseModel):
    id: str
    name: str
    platform: str

    model_config = {"from_attributes": True}


class ClientCountOut(BaseModel):
    id: int
    site_id: str
    ssid: str
    client_count: int
    polled_at: str

    model_config = {"from_attributes": True}


class LatestCountOut(BaseModel):
    site_id: str
    site_name: str
    ssid: str
    client_count: int
    polled_at: str


class DailyCountOut(BaseModel):
    site_id: str
    site_name: str
    ssid: str
    date: str
    max_count: int
    avg_count: float
