from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import UniqueConstraint, create_engine, inspect, text
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
    sync_schema(engine)
    _seed_default_units(engine)


def _seed_default_units(engine: Engine) -> None:
    # Lokaler Import, damit db.py (generische Infrastruktur) nicht bei jedem Modulimport von
    # app.services abhaengt - nur zur Laufzeit hier gebraucht.
    from app.services import unit_service

    with Session(engine) as session:
        unit_service.ensure_default_units(session)
        session.commit()


def sync_schema(engine: Engine) -> None:
    """Ergaenzt fehlende Spalten auf bereits bestehenden Tabellen (leichtgewichtiger Ersatz fuer Alembic).

    create_all() legt nur komplett neue Tabellen an; bestehende SQLite-Dateien aus
    frueheren App-Versionen bekommen neu hinzugekommene, nullable Spalten sonst nie.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue
            existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing_columns:
                    continue
                ddl_type = column.type.compile(dialect=engine.dialect)
                connection.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {ddl_type}'))
                if column.unique:
                    # SQLite's ADD COLUMN kann keine UNIQUE-Constraints mitbringen - separat nachziehen.
                    index_name = f"ux_{table.name}_{column.name}"
                    connection.execute(
                        text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}" ON "{table.name}" ("{column.name}")')
                    )

            # Mehrspaltige UniqueConstraints aus __table_args__ nachziehen, falls sie auf einer
            # bestehenden SQLite-Datei noch fehlen - gleiches Problem wie bei fehlenden Spalten:
            # create_all() legt sie nur auf brandneu erzeugten Tabellen an.
            existing_unique_column_sets = {
                tuple(sorted(uc["column_names"])) for uc in inspector.get_unique_constraints(table.name)
            }
            existing_unique_column_sets |= {
                tuple(sorted(ix["column_names"])) for ix in inspector.get_indexes(table.name) if ix["unique"]
            }
            for constraint in table.constraints:
                if not isinstance(constraint, UniqueConstraint):
                    continue
                column_names = tuple(sorted(col.name for col in constraint.columns))
                if column_names in existing_unique_column_sets:
                    continue
                index_name = constraint.name or f"ux_{table.name}_{'_'.join(column_names)}"
                columns_sql = ", ".join(f'"{name}"' for name in column_names)
                connection.execute(
                    text(f'CREATE UNIQUE INDEX IF NOT EXISTS "{index_name}" ON "{table.name}" ({columns_sql})')
                )


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
