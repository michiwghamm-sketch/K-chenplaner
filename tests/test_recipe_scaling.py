from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import Ingredient, IngredientPrice, Recipe, RecipeIngredient


@pytest.fixture()
def session_factory(tmp_path):
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "test.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    return create_session_factory(engine)


def test_recipe_and_ingredient_relationships_can_be_persisted(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(
            name="Nudeln",
            normalized_name="nudeln",
            default_unit="kg",
            category="Trockenware",
        )
        ingredient.prices.append(
            IngredientPrice(
                price_per_unit=Decimal("2.49"),
                unit="kg",
                year=2026,
                source="Preisliste",
            )
        )

        recipe = Recipe(
            name="Spaghetti Napoli",
            normalized_name="spaghetti napoli",
            meal_type="Hauptgericht",
            default_portions=20,
        )
        recipe.ingredients.append(
            RecipeIngredient(
                ingredient=ingredient,
                quantity=Decimal("0.150"),
                unit="kg",
                price_unit="kg",
                sort_order=1,
            )
        )
        session.add(recipe)

    with session_scope(session_factory) as session:
        stored_recipe = session.execute(
            select(Recipe).where(Recipe.normalized_name == "spaghetti napoli")
        ).scalar_one()
        assert stored_recipe.default_portions == 20
        assert len(stored_recipe.ingredients) == 1
        assert stored_recipe.ingredients[0].ingredient.name == "Nudeln"
        assert stored_recipe.ingredients[0].ingredient.prices[0].price_per_unit == Decimal("2.49")
