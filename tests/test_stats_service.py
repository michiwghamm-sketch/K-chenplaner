from datetime import date
from decimal import Decimal

from app.db import session_scope
from app.models import CampYear, Ingredient, IngredientPrice, MealPlanEntry, Recipe, RecipeIngredient
from app.services import stats_service


def _recipe_with_ingredient(session, name: str, *, diet_type: str | None, price: Decimal | None) -> Recipe:
    recipe = Recipe(name=name, normalized_name=name.lower(), default_portions=10, diet_type=diet_type)
    ingredient = Ingredient(name=f"{name} Zutat", normalized_name=f"{name.lower()} zutat", default_unit="kg")
    if price is not None:
        ingredient.prices.append(IngredientPrice(price_per_unit=price, unit="kg", year=2026))
    session.add_all([recipe, ingredient])
    session.flush()
    recipe.ingredients.append(
        RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg", price_unit="kg", sort_order=1)
    )
    return recipe


def test_recipe_counts_by_diet_type(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(Recipe(name="A", normalized_name="a", diet_type="Fleisch"))
        session.add(Recipe(name="B", normalized_name="b", diet_type="Fleisch"))
        session.add(Recipe(name="C", normalized_name="c", diet_type="Vegetarisch"))
        session.add(Recipe(name="D", normalized_name="d", diet_type=None))
        session.add(Recipe(name="E (inaktiv)", normalized_name="e", diet_type="Vegan", active=False))

    with session_scope(session_factory) as session:
        counts = stats_service.recipe_counts_by_diet_type(session)
        assert counts == {"Fleisch": 2, "Vegetarisch": 1, stats_service.UNKNOWN_DIET_TYPE_LABEL: 1}


def test_most_planned_recipes_counts_non_cancelled_entries_across_years(session_factory) -> None:
    with session_scope(session_factory) as session:
        popular = Recipe(name="Spaghetti", normalized_name="spaghetti", diet_type="Vegetarisch")
        rare = Recipe(name="Rippchen", normalized_name="rippchen", diet_type="Fleisch")
        unplanned = Recipe(name="Nie geplant", normalized_name="nie geplant")
        session.add_all([popular, rare, unplanned])
        session.flush()

        year_2025 = CampYear(year=2025, name="Zeltlager 2025")
        year_2026 = CampYear(year=2026, name="Zeltlager 2026")
        year_2025.meal_plan_entries.append(
            MealPlanEntry(meal_date=date(2025, 8, 1), meal_type="Mittagessen", recipe=popular, status="geplant")
        )
        year_2026.meal_plan_entries.extend(
            [
                MealPlanEntry(meal_date=date(2026, 8, 1), meal_type="Mittagessen", recipe=popular, status="geplant"),
                MealPlanEntry(meal_date=date(2026, 8, 2), meal_type="Mittagessen", recipe=rare, status="geplant"),
                MealPlanEntry(meal_date=date(2026, 8, 3), meal_type="Mittagessen", recipe=popular, status="abgesagt"),
            ]
        )
        session.add_all([year_2025, year_2026])

    with session_scope(session_factory) as session:
        ranked = stats_service.most_planned_recipes(session)
        assert [(r.recipe_name, r.plan_count) for r in ranked] == [("Spaghetti", 2), ("Rippchen", 1)]


def test_camp_year_costs_sums_non_cancelled_entries(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _recipe_with_ingredient(session, "Nudeln", diet_type=None, price=Decimal("2.00"))
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(meal_date=date(2026, 8, 1), meal_type="Mittagessen", recipe=recipe, planned_portions=10, status="geplant"),
                MealPlanEntry(meal_date=date(2026, 8, 2), meal_type="Mittagessen", recipe=recipe, planned_portions=999, status="abgesagt"),
            ]
        )
        session.add(camp_year)

    with session_scope(session_factory) as session:
        costs = stats_service.camp_year_costs(session)
        assert len(costs) == 1
        assert costs[0].year == 2026
        assert costs[0].total_portions == 10
        # Grundrezept fuer 10 Portionen braucht 1kg (2.00 EUR/kg); geplante 10 Portionen = Faktor 1.0.
        assert costs[0].total_cost == Decimal("2.00")


def test_average_recipe_cost_ignores_unpriced_recipes(session_factory) -> None:
    with session_scope(session_factory) as session:
        _recipe_with_ingredient(session, "Teuer", diet_type=None, price=Decimal("10.00"))
        _recipe_with_ingredient(session, "Guenstig", diet_type=None, price=Decimal("2.00"))
        _recipe_with_ingredient(session, "Unbepreist", diet_type=None, price=None)

    with session_scope(session_factory) as session:
        result = stats_service.average_recipe_cost(session)
        assert result.recipes_total == 3
        assert result.recipes_considered == 2
        assert result.average_total_cost == Decimal("6.00")
