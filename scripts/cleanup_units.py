from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402

from app.config import AppConfig  # noqa: E402
from app.db import initialize_database  # noqa: E402
from app.models import Ingredient, IngredientPrice, RecipeIngredient, ShoppingListItem  # noqa: E402
from app.services import unit_service, validation_service  # noqa: E402
from app.services.backup_service import create_backup  # noqa: E402

# (Modell, Spaltenname, Anzeige-Label)
TARGET_COLUMNS = [
    (Ingredient, "default_unit", "ingredients.default_unit"),
    (RecipeIngredient, "unit", "recipe_ingredients.unit"),
    (RecipeIngredient, "price_unit", "recipe_ingredients.price_unit"),
    (ShoppingListItem, "unit", "shopping_list_items.unit"),
    (IngredientPrice, "unit", "ingredient_prices.unit"),
]


@dataclass
class ColumnChange:
    label: str
    old_value: str
    new_value: str
    count: int = 0


@dataclass
class UnknownValue:
    label: str
    old_value: str
    attempted_value: str
    count: int = 0


@dataclass
class UnitCleanupResult:
    changes: list[ColumnChange]
    unknown: list[UnknownValue]
    # (Zutat, Rezept, verwendete Einheit, Standardeinheit der Zutat) - Altdaten, die auch nach der
    # Bereinigung nicht zur Standardeinheit ihrer Zutat passen und manuell geprueft werden muessen.
    mismatches: list[tuple[str, str, str, str]]
    backup_path: Path | None


def run_cleanup(config: AppConfig, *, apply: bool) -> UnitCleanupResult:
    """Bereinigt Freitext-Einheiten (v. a. das urspruengliche '€/kg'-Problem) auf die Pool-Schreibweise.

    Mit apply=False (Standard/Trockenlauf) wird nichts dauerhaft gespeichert - die Aenderungen
    werden trotzdem innerhalb der Session angewendet, damit der Bericht (insbesondere die
    Inkompatibilitaets-Pruefung am Ende) den Zustand NACH der Bereinigung zeigt, aber am Ende wird
    explizit zurueckgerollt statt committet. Mit apply=True wird vorher ein Backup angelegt.

    Werte, die sich nicht eindeutig auf eine Pool-Einheit abbilden lassen, werden NIEMALS geraten -
    sie landen in 'unknown' und bleiben unveraendert, fuer manuelle Pruefung.
    """
    _, engine, session_factory = initialize_database(config)

    backup_path: Path | None = None
    if apply:
        backup_path = create_backup(config)

    changes: dict[tuple[str, str, str], ColumnChange] = {}
    unknown: dict[tuple[str, str, str], UnknownValue] = {}

    session = session_factory()
    try:
        known_names = {unit.name for unit in unit_service.list_units(session, active_only=False)}

        for model, column_name, label in TARGET_COLUMNS:
            rows = session.execute(select(model)).scalars().all()
            for row in rows:
                old_value = getattr(row, column_name)
                if not old_value:
                    continue
                new_value = unit_service.canonicalize(session, old_value)
                if new_value == old_value:
                    continue

                if new_value and new_value in known_names:
                    key = (label, old_value, new_value)
                    entry = changes.setdefault(
                        key, ColumnChange(label=label, old_value=old_value, new_value=new_value)
                    )
                    entry.count += 1
                    # Immer in der Session anwenden (auch im Trockenlauf), damit die
                    # Inkompatibilitaets-Pruefung unten den Zustand NACH der Bereinigung sieht.
                    setattr(row, column_name, new_value)
                else:
                    key = (label, old_value, new_value or "")
                    entry = unknown.setdefault(
                        key, UnknownValue(label=label, old_value=old_value, attempted_value=new_value or "")
                    )
                    entry.count += 1

        session.flush()

        mismatches = [
            (ingredient.name, recipe.name, link.unit, ingredient.default_unit or "")
            for recipe, ingredient, link in validation_service.find_recipe_ingredient_unit_mismatches(session)
        ]

        if apply:
            session.commit()
        else:
            session.rollback()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return UnitCleanupResult(
        changes=sorted(changes.values(), key=lambda c: (c.label, c.old_value)),
        unknown=sorted(unknown.values(), key=lambda u: (u.label, u.old_value)),
        mismatches=sorted(mismatches),
        backup_path=backup_path,
    )


def write_report(project_root: Path, result: UnitCleanupResult, *, applied: bool) -> Path:
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    report_path = docs_dir / "unit_cleanup_report.md"

    lines = [
        "# Einheiten-Bereinigung",
        "",
        f"- Ausgefuehrt am: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Modus: {'angewendet' if applied else 'Trockenlauf (nichts geaendert)'}",
        f"- Backup: {result.backup_path if result.backup_path else '(kein Backup, Trockenlauf)'}",
        f"- Bereinigte Wertevarianten: {len(result.changes)} (betrifft {sum(c.count for c in result.changes)} Datensätze)",
        f"- Nicht automatisch zuordenbare Werte: {len(result.unknown)}",
        f"- Rezeptzutaten mit weiterhin inkompatibler Einheit: {len(result.mismatches)}",
        "",
        "## Bereinigte Wertevarianten",
        "",
    ]
    if not result.changes:
        lines.append("Keine bereinigungsbeduerftigen Werte gefunden.")
    else:
        lines.append("| Feld | Alter Wert | Neuer Wert | Anzahl Datensätze |")
        lines.append("| --- | --- | --- | --- |")
        for change in result.changes:
            lines.append(f"| {change.label} | `{change.old_value}` | `{change.new_value}` | {change.count} |")

    lines += ["", "## Nicht automatisch zuordenbare Werte", ""]
    if not result.unknown:
        lines.append("Keine.")
    else:
        lines.append(
            "Diese Werte konnten keiner Einheit im Pool zugeordnet werden und wurden **nicht** "
            "veraendert. Bitte manuell pruefen (Zutat/Zeile korrigieren oder die Einheit ueber "
            "'Einstellungen -> Einheiten verwalten' im Pool anlegen)."
        )
        lines.append("")
        lines.append("| Feld | Wert | Versuchte Zuordnung | Anzahl Datensätze |")
        lines.append("| --- | --- | --- | --- |")
        for entry in result.unknown:
            lines.append(f"| {entry.label} | `{entry.old_value}` | `{entry.attempted_value}` | {entry.count} |")

    lines += ["", "## Rezeptzutaten mit weiterhin inkompatibler Einheit", ""]
    if not result.mismatches:
        lines.append("Keine.")
    else:
        lines.append(
            "Diese Rezeptzutaten verwenden nach der Bereinigung eine Einheit, die nicht zur "
            "Standardeinheit ihrer Zutat passt (z. B. unterschiedliche Art wie Masse vs. Stueck). "
            "Bitte in der Rezeptansicht pruefen und die Menge/Einheit oder die Standardeinheit der "
            "Zutat korrigieren."
        )
        lines.append("")
        lines.append("| Zutat | Rezept | Verwendete Einheit | Standardeinheit der Zutat |")
        lines.append("| --- | --- | --- | --- |")
        for ingredient_name, recipe_name, unit, default_unit in result.mismatches:
            lines.append(f"| {ingredient_name} | {recipe_name} | {unit} | {default_unit or '(keine)'} |")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bereinigt Freitext-Mengeneinheiten (v. a. '€/kg'-artige Werte) auf die Pool-Schreibweise."
    )
    parser.add_argument("--db-path", help="Optionaler Pfad zur SQLite-Datenbank.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aenderungen wirklich speichern (legt vorher automatisch ein Backup an). Ohne dieses "
        "Flag passiert nur ein Trockenlauf, es wird nichts gespeichert.",
    )
    args = parser.parse_args()

    config = AppConfig.load(project_root=PROJECT_ROOT, database_path=Path(args.db_path) if args.db_path else None)
    result = run_cleanup(config, apply=args.apply)
    report_path = write_report(PROJECT_ROOT, result, applied=args.apply)

    print(f"Datenbank: {config.database_path}")
    print(f"Modus: {'angewendet' if args.apply else 'Trockenlauf'}")
    if result.backup_path:
        print(f"Backup erstellt: {result.backup_path}")
    print(f"Bereinigte Wertevarianten: {len(result.changes)} (betrifft {sum(c.count for c in result.changes)} Datensätze)")
    for change in result.changes:
        print(f"  {change.label}: {change.old_value!r} -> {change.new_value!r} ({change.count}x)")
    print(f"Nicht automatisch zuordenbare Werte: {len(result.unknown)}")
    for entry in result.unknown:
        print(f"  {entry.label}: {entry.old_value!r} ({entry.count}x) - bitte manuell pruefen")
    print(f"Rezeptzutaten mit weiterhin inkompatibler Einheit: {len(result.mismatches)}")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
