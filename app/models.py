from sqlalchemy import Column, Integer, String, Index
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Site(Base):
    __tablename__ = "sites"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    platform = Column(String, nullable=False)  # mist | cisco9800 | cisco5505
    config_json = Column(String, nullable=False)  # JSON blob (host, creds refs, etc.)


class ClientCount(Base):
    __tablename__ = "client_counts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    site_id = Column(String, nullable=False)
    ssid = Column(String, nullable=False)
    client_count = Column(Integer, nullable=False)
    polled_at = Column(String, nullable=False)  # ISO8601 UTC


Index("idx_cc_site_time", ClientCount.site_id, ClientCount.polled_at)
