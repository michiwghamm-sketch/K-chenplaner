from __future__ import annotations

from decimal import Decimal

import pytest

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import CampYear, Ingredient, IngredientPrice, MealPlanEntry, Recipe, RecipeIngredient


@pytest.fixture()
def session_factory(tmp_path):
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "test.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    return create_session_factory(engine)


@pytest.fixture()
def seeded_camp_year_id(session_factory) -> int:
    """Legt ein Camp-Jahr mit einem Rezept, einer Zutat, einem Preis und einer geplanten Mahlzeit an."""
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg")
        ingredient.prices.append(
            IngredientPrice(price_per_unit=Decimal("2.00"), unit="kg", year=2026, source="Preisliste")
        )

        recipe = Recipe(
            name="Spaghetti Napoli",
            normalized_name="spaghetti napoli",
            meal_type="Hauptgericht",
            default_portions=10,
        )
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("0.100"), unit="kg", price_unit="kg", sort_order=1)
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        camp_year.meal_plan_entries.append(
            MealPlanEntry(
                meal_date=None,
                meal_type="Mittagessen",
                recipe=recipe,
                planned_portions=20,
                status="geplant",
            )
        )
        session.add(camp_year)
        session.flush()
        return camp_year.id
