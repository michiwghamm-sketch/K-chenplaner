from decimal import Decimal

import pytest

from app.db import session_scope
from app.models import CampYear, Ingredient, Recipe, RecipeIngredient
from app.services import feedback_service, recipe_service


def _build_recipe(session) -> Recipe:
    recipe = Recipe(name="Semmelknoedel mit Schweinebraten", normalized_name="semmelknoedel", default_portions=10)
    session.add(recipe)
    session.flush()
    return recipe


def test_create_component_and_assign_ingredients_groups_cost_lines(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        knoedel = recipe_service.create_component(session, recipe, "Semmelknoedel")
        sauce = recipe_service.create_component(session, recipe, "Soße")

        bread = Ingredient(name="Semmelbroesel", normalized_name="semmelbroesel", default_unit="kg")
        flour = Ingredient(name="Mehl", normalized_name="mehl", default_unit="kg")
        session.add_all([bread, flour])
        session.flush()

        recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=bread.id, quantity=Decimal("1.000"), unit="kg", component_id=knoedel.id
        )
        recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=flour.id, quantity=Decimal("0.500"), unit="kg", component_id=sauce.id
        )
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        result = recipe_service.calculate_recipe_cost(session, recipe, portions=10)
        component_names = {line.ingredient_name: line.component_name for line in result.lines}
        assert component_names["Semmelbroesel"] == "Semmelknoedel"
        assert component_names["Mehl"] == "Soße"


def test_ingredient_without_component_falls_back_to_unassigned_label(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        ingredient = Ingredient(name="Salz", normalized_name="salz", default_unit="kg")
        session.add(ingredient)
        session.flush()
        recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("0.010"), unit="kg"
        )
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        result = recipe_service.calculate_recipe_cost(session, recipe, portions=10)
        assert result.lines[0].component_name == recipe_service.UNASSIGNED_COMPONENT_LABEL


def test_delete_component_keeps_ingredients_and_unassigns_them(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        component = recipe_service.create_component(session, recipe, "Fuellung")
        ingredient = Ingredient(name="Petersilie", normalized_name="petersilie", default_unit="kg")
        session.add(ingredient)
        session.flush()
        link = recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("0.020"), unit="kg", component_id=component.id
        )
        session.flush()
        link_id = link.id
        component_id = component.id
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        component = next(c for c in recipe.components if c.id == component_id)
        recipe_service.delete_component(session, component)

    with session_scope(session_factory) as session:
        link = session.get(RecipeIngredient, link_id)
        assert link is not None
        assert link.component_id is None


def test_create_version_snapshot_increments_version_number(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        recipe_service.create_version_snapshot(session, recipe, change_note="Erste Version")
        recipe_service.create_version_snapshot(session, recipe, change_note="Zweite Version")
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        versions = recipe_service.list_versions(recipe)
        assert [v.version_number for v in versions] == [2, 1]
        assert versions[0].change_note == "Zweite Version"


def test_scale_recipe_ingredients_saves_previous_state_and_updates_quantities(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        ingredient = Ingredient(name="Kartoffeln", normalized_name="kartoffeln", default_unit="kg")
        session.add(ingredient)
        session.flush()
        recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("1.000"), unit="kg"
        )
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        recipe_service.scale_recipe_ingredients(session, recipe, Decimal("0.900"))

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        assert recipe.ingredients[0].quantity == Decimal("0.900")
        versions = recipe_service.list_versions(recipe)
        assert len(versions) == 1
        snapshot = recipe_service.parse_version_snapshot(versions[0])
        assert snapshot[0]["quantity"] == "1.000"
        assert versions[0].scale_factor == Decimal("0.900")


def test_scale_recipe_ingredients_rejects_non_positive_factor(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        with pytest.raises(ValueError):
            recipe_service.scale_recipe_ingredients(session, recipe, Decimal("0"))


def test_update_ingredient_quantity_versions_before_changing(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        ingredient = Ingredient(name="Zwiebeln", normalized_name="zwiebeln", default_unit="kg")
        session.add(ingredient)
        session.flush()
        link = recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("0.300"), unit="kg"
        )
        session.flush()
        recipe_id = recipe.id
        link_id = link.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        link = session.get(RecipeIngredient, link_id)
        recipe_service.update_ingredient_quantity(session, recipe, link, quantity=Decimal("0.400"))

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        link = session.get(RecipeIngredient, link_id)
        assert link.quantity == Decimal("0.400")
        versions = recipe_service.list_versions(recipe)
        assert len(versions) == 1
        snapshot = recipe_service.parse_version_snapshot(versions[0])
        assert snapshot[0]["quantity"] == "0.300"


def test_suggested_scale_factor_uses_latest_feedback(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        session.flush()
        for year, cooked in ((2024, 11), (2026, 17)):
            camp_year = CampYear(year=year, name=f"Zeltlager {year}")
            session.add(camp_year)
            session.flush()
            feedback_service.record_feedback(
                session,
                camp_year=camp_year,
                recipe=recipe,
                planned_portions=20,
                cooked_portions=cooked,
            )
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        factor = recipe_service.suggested_scale_factor(recipe)
        assert factor == Decimal("0.850")


def test_suggested_scale_factor_none_without_feedback(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        assert recipe_service.suggested_scale_factor(recipe) is None
