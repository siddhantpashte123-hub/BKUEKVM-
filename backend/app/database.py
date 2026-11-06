"""SQLAlchemy engine, session factory and declarative base."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings

def database_connect_args(database_url: str) -> dict:
    """Use decoded text for psycopg, including on SQL_ASCII databases.

    This configures only this connection, never the PostgreSQL server or the
    stored database encoding. Existing SQL_ASCII data must be valid UTF-8.
    Preserve an explicitly configured client_encoding in the URL.
    """
    url = make_url(database_url)
    if url.get_backend_name() == "sqlite":
        return {"check_same_thread": False}
    if url.drivername == "postgresql+psycopg" and "client_encoding" not in url.query:
        return {"client_encoding": "UTF8"}
    return {}


connect_args = database_connect_args(settings.database_url)
engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
