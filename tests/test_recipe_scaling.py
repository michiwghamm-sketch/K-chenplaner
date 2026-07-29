from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import Ingredient, IngredientPrice, Recipe, RecipeIngredient
from app.services import recipe_service


def test_recipe_and_ingredient_relationships_can_be_persisted(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(
            name="Nudeln",
            normalized_name="nudeln",
            default_unit="kg",
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


def test_scale_recipe_multiplies_quantities_by_portion_ratio(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Reis", normalized_name="reis", default_unit="kg")
        recipe = Recipe(name="Reispfanne", normalized_name="reispfanne", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("0.100"), unit="kg", price_unit="kg", sort_order=1)
        )
        session.add(recipe)
        session.flush()
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        scaled = recipe_service.scale_recipe(recipe, 25)
        assert scaled[0].quantity == Decimal("2.500")
        assert scaled[0].unit == "kg"


def test_scale_recipe_rejects_non_positive_portions(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Salat", normalized_name="salat", default_portions=10)
        session.add(recipe)
        session.flush()
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        with pytest.raises(ValueError):
            recipe_service.scale_recipe(recipe, 0)


def test_calculate_recipe_cost_uses_best_known_price_and_flags_missing_prices(session_factory) -> None:
    with session_scope(session_factory) as session:
        priced_ingredient = Ingredient(name="Kartoffeln", normalized_name="kartoffeln", default_unit="kg")
        priced_ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("1.00"), unit="kg", year=2026))
        unpriced_ingredient = Ingredient(name="Geheimzutat", normalized_name="geheimzutat", default_unit="kg")

        recipe = Recipe(name="Eintopf", normalized_name="eintopf", default_portions=10)
        recipe.ingredients.extend(
            [
                RecipeIngredient(ingredient=priced_ingredient, quantity=Decimal("1.000"), unit="kg", price_unit="kg", sort_order=1),
                RecipeIngredient(ingredient=unpriced_ingredient, quantity=Decimal("0.500"), unit="kg", price_unit="kg", sort_order=2),
            ]
        )
        session.add(recipe)
        session.flush()
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        result = recipe_service.calculate_recipe_cost(session, recipe, portions=20, year=2026)
        # 1.000 kg per portion * 20 portions * 1.00 EUR = 20.00 EUR total; unpriced ingredient flagged as missing.
        assert result.total_cost == Decimal("20.00")
        assert result.cost_per_portion == Decimal("1.00")
        assert result.missing_price_ingredients == ["Geheimzutat"]

        assert len(result.lines) == 2
        priced_line = next(line for line in result.lines if line.ingredient_name == "Kartoffeln")
        assert priced_line.quantity == Decimal("20.000")
        assert priced_line.line_cost == Decimal("20.00")
        missing_line = next(line for line in result.lines if line.ingredient_name == "Geheimzutat")
        assert missing_line.price_per_unit is None
        assert missing_line.line_cost is None


def test_calculate_recipe_cost_uses_only_selected_price_year(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Reis", normalized_name="reis", default_unit="kg")
        ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("1.00"), unit="kg", year=2024))
        recipe = Recipe(name="Reistopf", normalized_name="reistopf", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg", price_unit="kg", sort_order=1)
        )
        session.add(recipe)
        session.flush()
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        result = recipe_service.calculate_recipe_cost(session, recipe, portions=10, year=2026)

        assert result.total_cost == Decimal("0.00")
        assert result.cost_per_portion == Decimal("0.00")
        assert result.missing_price_ingredients == ["Reis"]
