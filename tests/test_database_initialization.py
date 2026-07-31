from sqlalchemy import inspect

from app.config import AppConfig
from app.db import check_connectivity, check_sqlite_integrity, create_engine_from_config, init_database


def test_init_database_creates_expected_tables(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "schema.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert {
        "ingredients",
        "ingredient_aliases",
        "ingredient_prices",
        "ingredient_price_profiles",
        "open_prices_categories",
        "recipes",
        "recipe_ingredients",
        "camp_years",
        "meal_plan_entries",
        "recipe_feedback",
        "shopping_lists",
        "shopping_list_items",
        "app_settings",
        "import_runs",
        "import_issues",
    }.issubset(table_names)
    assert check_sqlite_integrity(engine) == "ok"
    assert check_connectivity(engine) == "ok"
