from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import get_settings


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker | None = None


def init_engine(url: str | None = None):
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    kwargs = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
    if url.startswith("sqlite:///"):
        from pathlib import Path

        Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(_engine, "connect")
        def _fk(dbapi_conn, _):  # pragma: no cover - sqlite pragma
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    from . import models  # noqa: F401  (register tables)
    Base.metadata.create_all(_engine)
    return _engine


def get_engine():
    if _engine is None:
        init_engine()
    return _engine


def SessionLocal() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()  # type: ignore[misc]


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
