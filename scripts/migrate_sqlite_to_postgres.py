"""Kopiert alle Daten aus einer lokalen SQLite-Datei in eine Postgres-Zieldatenbank (z. B. Neon).

Aufruf:
    .venv\\Scripts\\python.exe scripts\\migrate_sqlite_to_postgres.py ^
        --sqlite-path instance\\zeltlager_kueche.sqlite3 ^
        --postgres-url postgresql://user:pw@host/dbname

Legt das Schema auf der Zieldatenbank an (falls noch nicht vorhanden) und kopiert alle Tabellen
in FK-sicherer Reihenfolge inkl. Primaerschluessel. Bereits vorhandene Zeilen (gleicher
Primaerschluessel) werden uebersprungen - das Skript kann also gefahrlos mehrfach laufen.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Integer, create_engine, select, text  # noqa: E402
from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402

from app.config import normalize_postgres_url  # noqa: E402
from app.models import Base  # noqa: E402


POSTGRES_MAX_QUERY_PARAMS = 65535


def copy_table(source_engine: Engine, target_engine: Engine, table) -> int:
    with source_engine.connect() as source_conn:
        rows = [dict(row._mapping) for row in source_conn.execute(select(table))]
    if not rows:
        return 0

    # Postgres erlaubt maximal 65535 Query-Parameter - bei vielen Zeilen/Spalten (z. B.
    # open_prices_categories) muss der Insert daher in Haeppchen aufgeteilt werden.
    batch_size = max(1, POSTGRES_MAX_QUERY_PARAMS // max(1, len(table.columns)))
    pk_columns = [column.name for column in table.primary_key.columns]
    with target_engine.begin() as target_conn:
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            statement = pg_insert(table).values(batch)
            statement = statement.on_conflict_do_nothing(index_elements=pk_columns)
            target_conn.execute(statement)
    return len(rows)


def reset_sequences(target_engine: Engine) -> None:
    """Nach dem Kopieren mit expliziten Primaerschluesseln stehen Postgres-Sequences (SERIAL)
    sonst auf 1 - die naechste automatische Einfuegung wuerde mit vorhandenen IDs kollidieren."""
    with target_engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            pk_columns = list(table.primary_key.columns)
            if len(pk_columns) != 1 or not isinstance(pk_columns[0].type, Integer):
                continue
            column_name = pk_columns[0].name
            connection.execute(
                text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', '{column_name}'), "
                    f"COALESCE((SELECT MAX({column_name}) FROM {table.name}), 1), "
                    f"(SELECT MAX({column_name}) FROM {table.name}) IS NOT NULL)"
                )
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite-path", type=Path, required=True, help="Pfad zur lokalen SQLite-Datei")
    parser.add_argument("--postgres-url", required=True, help="Ziel-Connection-String (postgresql://...)")
    args = parser.parse_args()

    if not args.sqlite_path.exists():
        print(f"SQLite-Datei nicht gefunden: {args.sqlite_path}", file=sys.stderr)
        return 1

    source_engine = create_engine(f"sqlite:///{args.sqlite_path.as_posix()}", future=True)
    target_engine = create_engine(normalize_postgres_url(args.postgres_url), future=True)

    print("Lege Schema auf der Zieldatenbank an ...")
    Base.metadata.create_all(target_engine)

    for table in Base.metadata.sorted_tables:
        count = copy_table(source_engine, target_engine, table)
        print(f"  {table.name}: {count} Zeilen kopiert")

    print("Setze Postgres-Sequences auf den aktuellen Hoechststand ...")
    reset_sequences(target_engine)

    print("Fertig.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
