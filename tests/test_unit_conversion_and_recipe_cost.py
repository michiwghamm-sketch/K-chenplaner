from decimal import Decimal

from app.db import session_scope
from app.models import Ingredient, IngredientPrice, Recipe
from app.services import price_service, recipe_service


def test_convert_price_per_unit_supports_mass_units() -> None:
    converted = price_service.convert_price_per_unit(Decimal("6.00"), from_unit="kg", to_unit="g")
    assert converted == Decimal("0.006")


def test_normalize_unit_accepts_price_style_units() -> None:
    assert price_service.normalize_unit("€/kg") == "kg"
    assert price_service.normalize_unit("EUR/kg") == "kg"
    assert price_service.normalize_unit("Euro pro kg") == "kg"


def test_calculate_recipe_cost_converts_price_unit_to_recipe_unit(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg")
        ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("4.00"), unit="kg", year=2026))
        recipe = Recipe(name="Nudeltopf", normalized_name="nudeltopf", default_portions=10)
        session.add_all([ingredient, recipe])
        session.flush()
        recipe_service.add_ingredient_to_recipe(
            session,
            recipe,
            ingredient_id=ingredient.id,
            quantity=Decimal("250.000"),
            unit="g",
            price_unit="g",
        )

    with session_scope(session_factory) as session:
        recipe = session.query(Recipe).filter_by(normalized_name="nudeltopf").one()
        result = recipe_service.calculate_recipe_cost(session, recipe, year=2026)

        assert result.total_cost == Decimal("1.00")
        assert result.lines[0].price_per_unit == Decimal("0.0040")
