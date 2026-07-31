"""Synchronisiert den lokalen Offline-Cache mit der geteilten Cloud-Datenbank.

Ablauf (siehe SettingsView._sync_now() fuer die Bedienoberflaeche):

1. `analyze()` vergleicht lokalen Cache und Cloud-DB rein lesend und liefert einen Plan:
   welche lokalen Zeilen gefahrlos hochgeladen werden koennen, und welche Zeilen echte
   Konflikte sind (seit dem letzten Sync auf beiden Seiten veraendert).
2. Der Aufrufer laesst echte Konflikte vom Nutzer entscheiden (lokale oder Cloud-Version).
3. `apply()` laedt die freigegebenen Zeilen hoch (inkl. Verschieben von Primaerschluesseln
   fuer offline neu angelegte Zeilen, damit zwei Leute nicht zufaellig dieselbe ID vergeben),
   spiegelt den lokalen Cache danach komplett aus der Cloud zurueck und aktualisiert den
   Sync-Zeitstempel.

Bewusste Einschraenkung: Loeschungen werden nicht synchronisiert (kein Tombstone-Tracking) -
offline geloeschte Zeilen tauchen nach dem Sync wieder auf, wenn sie in der Cloud noch
existieren. Fuer eine kleine, vertraute Gruppe ist "nichts geht verloren" wichtiger als
perfekte Loeschsynchronisation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import Table, insert, select
from sqlalchemy.engine import Engine

from app.models import Base

POSTGRES_MAX_QUERY_PARAMS = 65535

# Spalte, die pro Tabelle als menschenlesbares Label in Konfliktdialogen dient - Fallback ist
# der Primaerschluessel, wenn keine passende Spalte existiert oder leer ist.
TABLE_LABEL_COLUMNS: dict[str, str] = {
    "ingredients": "name",
    "recipes": "name",
    "units": "name",
    "camp_years": "name",
    "recipe_steps": "title",
    "recipe_components": "name",
    "shopping_lists": "name",
    "open_prices_categories": "name_de",
}

_TABLES_BY_NAME: dict[str, Table] = {table.name: table for table in Base.metadata.sorted_tables}
_TABLE_HAS_UPDATED_AT: dict[str, bool] = {
    name: "updated_at" in table.columns for name, table in _TABLES_BY_NAME.items()
}
_TABLE_HAS_CREATED_AT: dict[str, bool] = {
    name: "created_at" in table.columns for name, table in _TABLES_BY_NAME.items()
}


def _normalize_value(value: Any) -> Any:
    """Macht Werte aus SQLite- und Postgres-Verbindungen vergleichbar: SQLite liefert
    zeitzonenlose datetimes zurueck, Postgres zeitzonenbehaftete - direkter Vergleich wuerde
    mit TypeError abbrechen. Sekundengenauigkeit reicht, Rundungsunterschiede im
    Mikrosekundenbereich sollen keine Phantom-Konflikte erzeugen."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=0)
    return value


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: _normalize_value(value) for key, value in row.items()}


def _fetch_rows(engine: Engine, table: Table) -> dict[tuple, dict[str, Any]]:
    pk_columns = [column.name for column in table.primary_key.columns]
    rows: dict[tuple, dict[str, Any]] = {}
    with engine.connect() as connection:
        for row in connection.execute(select(table)):
            mapping = _normalize_row(dict(row._mapping))
            key = tuple(mapping[column] for column in pk_columns)
            rows[key] = mapping
    return rows


@dataclass(slots=True)
class SyncConflict:
    table_name: str
    pk: tuple
    label: str
    local_row: dict[str, Any]
    cloud_row: dict[str, Any]

    @property
    def key(self) -> tuple[str, tuple]:
        return (self.table_name, self.pk)


@dataclass(slots=True)
class SyncPlan:
    # Offline neu angelegte Zeilen (existieren in der Cloud noch gar nicht) - werden ohne ihre
    # lokale ID eingefuegt, siehe _push_new_row(). Getrennt von updated_rows gehalten, weil eine
    # zufaellig gleiche lokale ID in der Cloud sonst faelschlich als "dieselbe Zeile" gelten wuerde.
    new_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    # Zeilen, die in der Cloud bereits unter derselben ID existieren und nur lokal veraendert wurden.
    updated_rows: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    conflicts: list[SyncConflict] = field(default_factory=list)
    is_first_sync: bool = False


@dataclass(slots=True)
class SyncReport:
    pushed_rows: int
    conflicts_resolved_local: int
    conflicts_resolved_cloud: int


def _table_label(table_name: str, row: dict[str, Any]) -> str:
    label_column = TABLE_LABEL_COLUMNS.get(table_name)
    if label_column and row.get(label_column):
        return str(row[label_column])
    pk_columns = [column.name for column in _TABLES_BY_NAME[table_name].primary_key.columns]
    return ", ".join(f"{column}={row.get(column)}" for column in pk_columns)


def read_last_synced_at(sync_state_path: Path) -> datetime | None:
    if not sync_state_path.exists():
        return None
    try:
        data = json.loads(sync_state_path.read_text(encoding="utf-8"))
        raw = data.get("last_synced_at")
        return datetime.fromisoformat(raw) if raw else None
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def write_last_synced_at(sync_state_path: Path, when: datetime) -> None:
    sync_state_path.write_text(json.dumps({"last_synced_at": when.isoformat()}), encoding="utf-8")


def analyze(local_engine: Engine, cloud_engine: Engine, last_synced_at: datetime | None) -> SyncPlan:
    plan = SyncPlan(is_first_sync=last_synced_at is None)
    normalized_last_sync = _normalize_value(last_synced_at) if last_synced_at else None

    for table in Base.metadata.sorted_tables:
        local_rows = _fetch_rows(local_engine, table)
        cloud_rows = _fetch_rows(cloud_engine, table)
        has_updated_at = _TABLE_HAS_UPDATED_AT[table.name]
        has_created_at = _TABLE_HAS_CREATED_AT[table.name]

        new_rows: list[dict[str, Any]] = []
        updated_rows: list[dict[str, Any]] = []
        for pk, local_row in local_rows.items():
            cloud_row = cloud_rows.get(pk)
            if cloud_row is None:
                new_rows.append(local_row)  # offline neu angelegt
                continue
            if local_row == cloud_row:
                continue  # unveraendert, nichts zu tun

            if has_created_at and normalized_last_sync is not None:
                # Beide Seiten haben unabhaengig voneinander eine neue Zeile angelegt, die
                # zufaellig dieselbe ID bekommen hat (z. B. Autoincrement auf beiden Seiten
                # gleich weit) - das ist kein Bearbeitungskonflikt derselben Zeile, sondern
                # zwei verschiedene Zeilen. Die lokale Zeile bekommt beim Push eine neue ID
                # (siehe apply()/_push_new_row), statt die fremde Cloud-Zeile zu ueberschreiben.
                local_is_new = local_row["created_at"] > normalized_last_sync
                cloud_is_new = cloud_row["created_at"] > normalized_last_sync
                if local_is_new and cloud_is_new:
                    new_rows.append(local_row)
                    continue

            if has_updated_at and normalized_last_sync is not None:
                local_changed = local_row["updated_at"] > normalized_last_sync
                cloud_changed = cloud_row["updated_at"] > normalized_last_sync
                if local_changed and not cloud_changed:
                    updated_rows.append(local_row)
                    continue
                if not local_changed:
                    continue  # nur die Cloud hat sich geaendert - kommt per Refresh rein

            # Kein updated_at, kein vorheriger Sync-Zeitpunkt, oder beide Seiten veraendert:
            # nicht automatisch entscheiden.
            plan.conflicts.append(
                SyncConflict(
                    table_name=table.name,
                    pk=pk,
                    label=_table_label(table.name, local_row),
                    local_row=local_row,
                    cloud_row=cloud_row,
                )
            )

        if new_rows:
            plan.new_rows[table.name] = new_rows
        if updated_rows:
            plan.updated_rows[table.name] = updated_rows

    return plan


def _dialect_insert(engine: Engine, table: Table):
    """Postgres (Cloud) und SQLite (Tests/lokaler Fallback) haben beide eine
    ON-CONFLICT-Upsert-API mit identischer Signatur, nur aus unterschiedlichen Modulen."""
    if engine.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as dialect_insert
    else:
        from sqlalchemy.dialects.sqlite import insert as dialect_insert
    return dialect_insert(table)


def _remap_row_fks(table: Table, row: dict[str, Any], remap: dict[str, dict[Any, Any]]) -> dict[str, Any]:
    remapped = dict(row)
    for fk in table.foreign_keys:
        target_table = fk.column.table.name
        table_remap = remap.get(target_table)
        if not table_remap:
            continue
        column_name = fk.parent.name
        current_value = remapped.get(column_name)
        if current_value in table_remap:
            remapped[column_name] = table_remap[current_value]
    return remapped


def _push_new_row(cloud_engine: Engine, table: Table, row: dict[str, Any]) -> Any:
    """Fuegt eine offline neu angelegte Zeile ein, OHNE ihre lokale ID zu uebernehmen - zwei
    offline arbeitende Personen koennten sonst dieselbe autoincrement-ID vergeben haben und
    sich gegenseitig ueberschreiben. Die Cloud vergibt eine neue ID, die zurueckgegeben wird,
    damit abhaengige Zeilen (z. B. Rezeptzutaten eines neuen Rezepts) darauf umgehaengt werden."""
    pk_columns = [column.name for column in table.primary_key.columns]
    single_pk = pk_columns[0] if len(pk_columns) == 1 else None
    insert_values = {key: value for key, value in row.items() if key != single_pk} if single_pk else row

    with cloud_engine.begin() as connection:
        if single_pk is not None:
            result = connection.execute(insert(table).returning(table.c[single_pk]), insert_values)
            return result.scalar_one()
        connection.execute(insert(table), insert_values)
        return None


def _push_existing_rows(cloud_engine: Engine, table: Table, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    pk_columns = [column.name for column in table.primary_key.columns]
    batch_size = max(1, POSTGRES_MAX_QUERY_PARAMS // max(1, len(table.columns)))
    with cloud_engine.begin() as connection:
        for start in range(0, len(rows), batch_size):
            batch = rows[start : start + batch_size]
            statement = _dialect_insert(cloud_engine, table).values(batch)
            update_columns = {
                column.name: statement.excluded[column.name] for column in table.columns if column.name not in pk_columns
            }
            statement = statement.on_conflict_do_update(index_elements=pk_columns, set_=update_columns)
            connection.execute(statement)


def refresh_local_cache_from_cloud(
    local_engine: Engine, cloud_engine: Engine, sync_state_path: Path | None = None
) -> None:
    """Ersetzt den kompletten Inhalt des lokalen Caches durch den aktuellen Cloud-Stand -
    einfacher und robuster als selektives Nachziehen einzelner Zeilen, und stellt sicher,
    dass beide Seiten nach dem Sync exakt uebereinstimmen. Wird `sync_state_path` mitgegeben,
    gilt der jetzige Zeitpunkt als neuer Sync-Referenzpunkt fuer kuenftige Konflikterkennung."""
    tables_reverse = list(reversed(Base.metadata.sorted_tables))
    with local_engine.begin() as connection:
        for table in tables_reverse:
            connection.execute(table.delete())

    for table in Base.metadata.sorted_tables:
        with cloud_engine.connect() as cloud_conn:
            rows = [dict(row._mapping) for row in cloud_conn.execute(select(table))]
        if not rows:
            continue
        with local_engine.begin() as local_conn:
            local_conn.execute(insert(table), rows)

    if sync_state_path is not None:
        write_last_synced_at(sync_state_path, datetime.now(timezone.utc))


def apply(
    local_engine: Engine,
    cloud_engine: Engine,
    plan: SyncPlan,
    resolutions: dict[tuple[str, tuple], Literal["local", "cloud"]],
    sync_state_path: Path,
) -> SyncReport:
    new_rows_by_table = {name: list(rows) for name, rows in plan.new_rows.items()}
    updated_rows_by_table = {name: list(rows) for name, rows in plan.updated_rows.items()}
    resolved_local = resolved_cloud = 0
    for conflict in plan.conflicts:
        choice = resolutions.get(conflict.key, "cloud")
        if choice == "local":
            # Der Konflikt betrifft per Definition eine in der Cloud bereits vorhandene Zeile
            # (sonst waere es kein Konflikt, sondern eine neue Zeile gewesen) - also immer Update.
            updated_rows_by_table.setdefault(conflict.table_name, []).append(conflict.local_row)
            resolved_local += 1
        else:
            resolved_cloud += 1

    remap: dict[str, dict[Any, Any]] = {}
    pushed_count = 0

    for table in Base.metadata.sorted_tables:
        new_rows = new_rows_by_table.get(table.name, [])
        updated_rows = updated_rows_by_table.get(table.name, [])
        if not new_rows and not updated_rows:
            continue

        pk_column_name = next(iter(table.primary_key.columns)).name if len(table.primary_key.columns) == 1 else None

        table_remap: dict[Any, Any] = {}
        for row in new_rows:
            remapped_row = _remap_row_fks(table, row, remap)
            old_pk = remapped_row.get(pk_column_name) if pk_column_name else None
            new_pk = _push_new_row(cloud_engine, table, remapped_row)
            if pk_column_name and new_pk is not None:
                table_remap[old_pk] = new_pk
            pushed_count += 1
        if table_remap:
            remap[table.name] = table_remap

        remapped_updated_rows = [_remap_row_fks(table, row, remap) for row in updated_rows]
        _push_existing_rows(cloud_engine, table, remapped_updated_rows)
        pushed_count += len(remapped_updated_rows)

    refresh_local_cache_from_cloud(local_engine, cloud_engine, sync_state_path)

    return SyncReport(
        pushed_rows=pushed_count,
        conflicts_resolved_local=resolved_local,
        conflicts_resolved_cloud=resolved_cloud,
    )
