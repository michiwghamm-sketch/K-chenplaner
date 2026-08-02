"""Lockert die NOT-NULL-Vorgabe auf shopping_list_item_allocations.shopping_list_item_id.

Hintergrund: Die Spalte stammt aus einem fruehen Zwischenstand des "Einkauf planen"-Features
und ist fachlich mittlerweile ueberholt (siehe Kommentar in app/models.py bei
ShoppingListItemAllocation.shopping_list_item_id) - eine Allocation repraesentiert eine
Zutat-Gesamtmenge, nicht mehr eine einzelne Wochenplan-Zeile. Weil app.db.sync_schema nur neue
Spalten ergaenzen, aber keine Constraints lockern kann (siehe dessen Docstring), muss das hier
einmalig manuell gegen die echte Datenbank laufen, bevor der Code die Spalte optional machen
bzw. ganz entfernen kann.

Nur fuer Postgres gedacht (die geteilte Cloud-DB) - SQLite unterstuetzt "ALTER COLUMN ...
DROP NOT NULL" nicht und lokale Installationen sind von dem eigentlichen Risiko (Cascade-Delete
ueber mehrere Nutzer hinweg) ohnehin nicht betroffen.

Aufruf:
    .venv\\Scripts\\python.exe scripts\\drop_allocation_item_fk_not_null.py ^
        --postgres-url postgresql://user:pw@host/dbname

Idempotent - kann gefahrlos mehrfach laufen (prueft vorher, ob die Spalte ueberhaupt noch
NOT NULL ist).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import create_engine, inspect, text  # noqa: E402

from app.config import normalize_postgres_url  # noqa: E402

TABLE = "shopping_list_item_allocations"
COLUMN = "shopping_list_item_id"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--postgres-url", required=True, help="Connection-String der Cloud-Datenbank (postgresql://...)")
    args = parser.parse_args()

    engine = create_engine(normalize_postgres_url(args.postgres_url), future=True)
    inspector = inspect(engine)

    if TABLE not in inspector.get_table_names():
        print(f"Tabelle '{TABLE}' existiert nicht - nichts zu tun.")
        return 0

    columns = {column["name"]: column for column in inspector.get_columns(TABLE)}
    column = columns.get(COLUMN)
    if column is None:
        print(f"Spalte '{COLUMN}' existiert nicht mehr - nichts zu tun.")
        return 0
    if column["nullable"]:
        print(f"Spalte '{COLUMN}' ist bereits nullable - nichts zu tun.")
        return 0

    print(f"Setze {TABLE}.{COLUMN} auf nullable ...")
    with engine.begin() as connection:
        connection.execute(text(f'ALTER TABLE "{TABLE}" ALTER COLUMN "{COLUMN}" DROP NOT NULL'))
    print("Fertig. Die Spalte kann jetzt in app/models.py als Optional[int] geführt werden")
    print("(oder, sobald niemand mehr eine alte App-Version mit der Pflichtspalte nutzt, ganz entfernt werden).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
