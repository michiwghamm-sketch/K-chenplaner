from decimal import Decimal

from app.db import session_scope
from app.models import NON_FOOD_CATEGORY, Ingredient, StandardShoppingItem
from app.ui.ingredients_view import _standard_item_ingredient_choices


def test_standard_item_choices_hide_recipe_ingredients(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe_ingredient = Ingredient(name="Aepfel", normalized_name="aepfel", default_unit="kg")
        non_food = Ingredient(
            name="Muellsaecke 60L",
            normalized_name="muellsaecke 60l",
            default_unit="Stk",
            category=NON_FOOD_CATEGORY,
        )
        legacy_standard_item = Ingredient(name="Grillkohle", normalized_name="grillkohle", default_unit="Stk")
        session.add_all([recipe_ingredient, non_food, legacy_standard_item])
        session.flush()
        session.add(
            StandardShoppingItem(
                ingredient=legacy_standard_item,
                default_quantity=Decimal("1.000"),
                default_unit="Stk",
                active=True,
            )
        )
        session.flush()

        names = {choice.name for choice in _standard_item_ingredient_choices(session)}

    assert names == {"Muellsaecke 60L", "Grillkohle"}
