from datetime import date
from decimal import Decimal

from app.db import session_scope
from app.models import CampYear, Ingredient, IngredientPrice, MealPlanEntry, Recipe
from app.services import validation_service


def test_find_missing_prices_and_units(session_factory) -> None:
    with session_scope(session_factory) as session:
        priced = Ingredient(name="Zucker", normalized_name="zucker", default_unit="kg")
        priced.prices.append(IngredientPrice(price_per_unit=Decimal("0.99"), unit="kg", year=2026))
        unpriced_with_unit = Ingredient(name="Salz", normalized_name="salz", default_unit="kg")
        unpriced_without_unit = Ingredient(name="Gewuerzmischung", normalized_name="gewuerzmischung")
        session.add_all([priced, unpriced_with_unit, unpriced_without_unit])

    with session_scope(session_factory) as session:
        missing_prices = {i.name for i in validation_service.find_missing_prices(session)}
        missing_units = {i.name for i in validation_service.find_missing_units(session)}
        assert missing_prices == {"Salz", "Gewuerzmischung"}
        assert missing_units == {"Gewuerzmischung"}


def test_find_recipes_without_ingredients_ignores_inactive(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(Recipe(name="Leeres Rezept", normalized_name="leeres rezept"))
        session.add(Recipe(name="Inaktives Rezept", normalized_name="inaktives rezept", active=False))

    with session_scope(session_factory) as session:
        empty_recipes = {r.name for r in validation_service.find_recipes_without_ingredients(session)}
        assert empty_recipes == {"Leeres Rezept"}


def test_find_meal_plan_without_portions_ignores_cancelled_entries(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Couscous Salat", normalized_name="couscous salat")
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(meal_date=date(2026, 8, 1), meal_type="Mittagessen", recipe=recipe, planned_portions=None, status="geplant"),
                MealPlanEntry(meal_date=date(2026, 8, 1), meal_type="Abendessen", recipe=recipe, planned_portions=None, status="abgesagt"),
                MealPlanEntry(meal_date=date(2026, 8, 1), meal_type="Fruehstueck", recipe=recipe, planned_portions=10, status="geplant"),
            ]
        )
        session.add_all([recipe, camp_year])
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        incomplete = validation_service.find_meal_plan_without_portions(session, camp_year)
        assert len(incomplete) == 1
        assert incomplete[0].meal_type == "Mittagessen"


def test_find_duplicate_ingredients_without_alias_detects_near_matches(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Paprika Pulver", normalized_name="paprika pulver"))
        session.add(Ingredient(name="Paprikapulver", normalized_name="paprikapulver"))
        session.add(Ingredient(name="Tomaten", normalized_name="tomaten"))

    with session_scope(session_factory) as session:
        duplicates = validation_service.find_duplicate_ingredients_without_alias(session)
        names = {(a.name, b.name) for a, b, _ratio in duplicates}
        assert ("Paprika Pulver", "Paprikapulver") in names
        assert not any("Tomaten" in pair for pair in names)
