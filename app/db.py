from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig
from app.models import Base


def create_engine_from_config(config: AppConfig, *, echo: bool = False) -> Engine:
    return create_engine(
        config.database_url,
        echo=echo,
        future=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def init_database(engine: Engine) -> None:
    Base.metadata.create_all(engine)


def initialize_database(
    config: AppConfig | None = None,
    *,
    echo: bool = False,
) -> tuple[AppConfig, Engine, sessionmaker[Session]]:
    resolved_config = config or AppConfig.load()
    engine = create_engine_from_config(resolved_config, echo=echo)
    init_database(engine)
    return resolved_config, engine, create_session_factory(engine)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_sqlite_integrity(engine: Engine) -> str:
    with engine.connect() as connection:
        result = connection.execute(text("PRAGMA integrity_check;"))
        row = result.fetchone()
    return row[0] if row else "unknown"


def database_exists(database_path: Path) -> bool:
    return database_path.exists()
