from decimal import Decimal

from sqlalchemy import select

from app.db import session_scope
from app.models import Ingredient, IngredientPrice, ShoppingList, ShoppingListItem, CampYear, Recipe
from app.services import data_cleanup_service


def test_cleanup_non_ingredient_entries_deletes_recipe_names_and_summary_rows(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Spaghetti Napoli", normalized_name="spaghetti napoli")
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(camp_year=camp_year, name="Einkaufsliste 2026")

        recipe_name_ingredient = Ingredient(name="Spaghetti Napoli", normalized_name="spaghetti napoli")
        recipe_name_ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("0.00"), unit="", source="Bad Import"))
        header_ingredient = Ingredient(name="Schnell-Check Preisliste", normalized_name="schnell check preisliste")
        header_ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("0.00"), unit="", source="Bad Import"))
        real_ingredient = Ingredient(name="Tomaten", normalized_name="tomaten", default_unit="kg")

        shopping_list.items.append(
            ShoppingListItem(ingredient=recipe_name_ingredient, quantity=Decimal("20.000"), unit="Portionen")
        )
        shopping_list.items.append(
            ShoppingListItem(ingredient=real_ingredient, quantity=Decimal("2.000"), unit="kg")
        )

        session.add_all([recipe, camp_year, shopping_list, recipe_name_ingredient, header_ingredient, real_ingredient])

    with session_scope(session_factory) as session:
        report = data_cleanup_service.cleanup_non_ingredient_entries(session)
        assert report.deleted_shopping_summary_count == 1
        assert "Spaghetti Napoli" in report.deleted_ingredient_names
        assert "Schnell-Check Preisliste" in report.deleted_ingredient_names

    with session_scope(session_factory) as session:
        names = [ingredient.name for ingredient in session.execute(select(Ingredient).order_by(Ingredient.name)).scalars()]
        assert names == ["Tomaten"]
        items = session.execute(select(ShoppingListItem)).scalars().all()
        assert len(items) == 1
        assert items[0].unit == "kg"
