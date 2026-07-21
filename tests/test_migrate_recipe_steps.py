from openpyxl import Workbook
from sqlalchemy import select

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import Recipe
from scripts.migrate_excel_to_sqlite import run_import


def build_workbook_with_steps(path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Preisliste"
    ws.append(["Zutat", "Preis", "Einheit", "Status", "Quelle / Shop", "Stand", "Preisnotiz"])

    recipe = wb.create_sheet("Testrezept")
    recipe["E2"] = "Testrezept"
    recipe["H6"] = 10
    recipe.append([])
    recipe.append(["Zutaten:", "Grundmenge:", "Einheit:", "Gesamtmenge", "Preis/kg:", "Gesamtpreis:"])
    recipe.append(["Nudeln", 0.1, "kg", 1, 2, 2])
    recipe.append(["Gesamtkosten:", None, None, None, None, 2])
    recipe.append(["Zubereitung: "])
    recipe.append([])
    # Schritte-Block: Titel (A), Anweisung (B), Dauer in Minuten steht in Spalte G - nicht C.
    recipe.append(["Schritte:", "Anweisung:", None, None, None, None, "Ungefaehre Dauer in min:"])
    recipe.append(["Wasser kochen", "Topf mit Wasser aufsetzen", None, None, None, None, 10])
    recipe.append(["Nudeln kochen", "Nudeln bissfest kochen", None, None, None, None, 8])
    recipe.append(["Gesamtdauer:", 18, "Minuten"])

    wb.save(path)


def test_migration_extracts_steps_with_correct_duration_column(tmp_path) -> None:
    workbook_path = tmp_path / "steps.xlsx"
    build_workbook_with_steps(workbook_path)

    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "steps.sqlite3")
    counters, _issues = run_import(workbook_path, config)
    assert counters.recipe_steps == 2

    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        recipe = session.execute(select(Recipe).where(Recipe.normalized_name == "testrezept")).scalar_one()
        steps = sorted(recipe.steps, key=lambda s: s.sort_order)
        assert [s.title for s in steps] == ["Wasser kochen", "Nudeln kochen"]
        assert [s.description for s in steps] == ["Topf mit Wasser aufsetzen", "Nudeln bissfest kochen"]
        # Regression: duration used to be read from column C (always empty) instead of G.
        assert [s.duration_minutes for s in steps] == [10, 8]


def test_migration_is_idempotent_for_steps(tmp_path) -> None:
    workbook_path = tmp_path / "steps.xlsx"
    build_workbook_with_steps(workbook_path)
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "steps.sqlite3")

    run_import(workbook_path, config)
    second_counters, _ = run_import(workbook_path, config)

    assert second_counters.recipe_steps == 0

    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        recipe = session.execute(select(Recipe).where(Recipe.normalized_name == "testrezept")).scalar_one()
        assert len(recipe.steps) == 2
