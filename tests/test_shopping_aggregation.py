from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import CampYear, Ingredient, MealPlanEntry, Recipe, ShoppingList, ShoppingListItem


@pytest.fixture()
def session_factory(tmp_path):
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "shopping.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    return create_session_factory(engine)


def test_camp_year_planning_and_shopping_list_roundtrip(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(
            year=2026,
            name="Zeltlager 2026",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 10),
        )
        recipe = Recipe(
            name="Chili sin Carne",
            normalized_name="chili sin carne",
            meal_type="Abendessen",
            default_portions=20,
        )
        ingredient = Ingredient(name="Kidneybohnen", normalized_name="kidneybohnen", default_unit="kg")
        shopping_list = ShoppingList(name="Haupteinkauf", camp_year=camp_year)
        shopping_list.items.append(
            ShoppingListItem(
                ingredient=ingredient,
                quantity=Decimal("4.500"),
                unit="kg",
                estimated_price_per_unit=Decimal("2.80"),
                estimated_total_price=Decimal("12.60"),
                linked_recipes_text="Chili sin Carne",
                status="offen",
            )
        )
        camp_year.meal_plan_entries.append(
            MealPlanEntry(
                meal_date=date(2026, 8, 2),
                weekday="Sonntag",
                meal_type="Abendessen",
                recipe=recipe,
                planned_portions=95,
                status="geplant",
            )
        )
        session.add(camp_year)
        session.add(shopping_list)

    with session_scope(session_factory) as session:
        stored_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        assert stored_year.meal_plan_entries[0].recipe.name == "Chili sin Carne"
        assert stored_year.shopping_lists[0].items[0].estimated_total_price == Decimal("12.60")
        assert stored_year.shopping_lists[0].items[0].linked_recipes_text == "Chili sin Carne"
