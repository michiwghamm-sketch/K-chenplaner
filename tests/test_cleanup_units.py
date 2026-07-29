from decimal import Decimal

from sqlalchemy import select

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import Ingredient, IngredientPrice, Recipe, RecipeIngredient
from scripts.cleanup_units import run_cleanup, write_report


def _make_config(tmp_path):
    return AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "cleanup.sqlite3")


def test_dry_run_reports_change_but_does_not_persist_it(tmp_path) -> None:
    config = _make_config(tmp_path)
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Mehl", normalized_name="mehl", default_unit="€/kg"))

    result = run_cleanup(config, apply=False)
    assert result.backup_path is None
    assert not (tmp_path / "backups").exists()
    assert any(
        c.label == "ingredients.default_unit" and c.old_value == "€/kg" and c.new_value == "kg"
        for c in result.changes
    )

    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient)).scalar_one()
        assert ingredient.default_unit == "€/kg"


def test_apply_persists_normalized_value_and_creates_backup(tmp_path) -> None:
    config = _make_config(tmp_path)
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Mehl", normalized_name="mehl", default_unit="€/kg"))

    result = run_cleanup(config, apply=True)
    assert result.backup_path is not None
    assert result.backup_path.exists()

    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient)).scalar_one()
        assert ingredient.default_unit == "kg"


def test_unmappable_value_is_left_untouched_and_reported_as_unknown(tmp_path) -> None:
    config = _make_config(tmp_path)
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Mysteriöse Zutat", normalized_name="mysterioese zutat", default_unit="Krug"))

    result = run_cleanup(config, apply=True)
    assert result.changes == []
    assert any(
        u.label == "ingredients.default_unit" and u.old_value == "Krug" for u in result.unknown
    )

    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient)).scalar_one()
        assert ingredient.default_unit == "Krug"


def test_reports_recipe_ingredient_with_incompatible_unit_after_cleanup(tmp_path) -> None:
    """Regression fuer die reale Datenlage: die '€/kg'-Bereinigung deckt teils zugrunde liegende,
    echte Inkonsistenzen auf (z. B. eine Zutat mit Standardeinheit 'kg', aber einer Rezeptzutat, die
    sie in 'Stk' verwendet) - die duerfen nicht automatisch geraten, sondern muessen gemeldet werden."""
    config = _make_config(tmp_path)
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Salat", normalized_name="salat", default_unit="Stk")
        session.add_all([recipe, ingredient])
        session.flush()
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg", sort_order=1)
        )

    result = run_cleanup(config, apply=False)
    assert ("Salat", "Testgericht", "kg", "Stk") in result.mismatches


def test_write_report_includes_all_sections(tmp_path) -> None:
    config = _make_config(tmp_path)
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Mehl", normalized_name="mehl", default_unit="€/kg")
        ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("1.50"), unit="Krug", year=2026))
        session.add(ingredient)

    result = run_cleanup(config, apply=True)
    report_path = write_report(tmp_path, result, applied=True)
    content = report_path.read_text(encoding="utf-8")

    assert "angewendet" in content
    assert "€/kg" in content
    assert "Krug" in content
    assert str(result.backup_path) in content
