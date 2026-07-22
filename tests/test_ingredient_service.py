from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import Ingredient, IngredientPrice, Recipe, RecipeIngredient, ShoppingList, ShoppingListItem, CampYear
from app.services import ingredient_service


def test_find_merge_candidates_detects_plural_variant(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        session.add(recipe)
        onion_singular = Ingredient(name="Zwiebel", normalized_name="zwiebel", default_unit="kg")
        onion_plural = Ingredient(name="Zwiebeln", normalized_name="zwiebeln", default_unit="kg")
        session.add_all([onion_singular, onion_plural])
        session.flush()
        recipe.ingredients.append(
            RecipeIngredient(ingredient=onion_singular, quantity=Decimal("0.100"), unit="kg", price_unit="kg", sort_order=1)
        )

    with session_scope(session_factory) as session:
        candidates = ingredient_service.find_merge_candidates(session)
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.reason == "Singular/Plural-Variante"
        # The variant actually used in a recipe should be the one that survives.
        assert candidate.keep.name == "Zwiebel"
        assert candidate.remove.name == "Zwiebeln"


def test_find_merge_candidates_skips_already_aliased_pairs(session_factory) -> None:
    with session_scope(session_factory) as session:
        onion = Ingredient(name="Zwiebel", normalized_name="zwiebel")
        session.add(onion)
        session.flush()
        ingredient_service.add_alias(session, onion, "Zwiebeln")

    with session_scope(session_factory) as session:
        candidates = ingredient_service.find_merge_candidates(session)
        assert candidates == []


def test_find_merge_candidates_ignores_unrelated_ingredients(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Zwiebel", normalized_name="zwiebel"))
        session.add(Ingredient(name="Tomate", normalized_name="tomate"))

    with session_scope(session_factory) as session:
        assert ingredient_service.find_merge_candidates(session) == []


def test_merge_ingredients_repoints_all_references_and_deletes_duplicate(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        keep = Ingredient(name="Zwiebel", normalized_name="zwiebel", default_unit="kg")
        remove = Ingredient(name="Zwiebeln", normalized_name="zwiebeln")
        remove.prices.append(IngredientPrice(price_per_unit=Decimal("1.50"), unit="kg", year=2026))
        session.add_all([recipe, camp_year, keep, remove])
        session.flush()

        recipe.ingredients.append(
            RecipeIngredient(ingredient=remove, quantity=Decimal("0.200"), unit="kg", price_unit="kg", sort_order=1)
        )
        shopping_list = ShoppingList(name="Liste", camp_year=camp_year)
        shopping_list.items.append(ShoppingListItem(ingredient=remove, quantity=Decimal("1.000"), unit="kg"))
        session.add(shopping_list)
        session.flush()
        keep_id, remove_id, recipe_id, shopping_list_id = keep.id, remove.id, recipe.id, shopping_list.id

    with session_scope(session_factory) as session:
        keep = session.get(Ingredient, keep_id)
        remove = session.get(Ingredient, remove_id)
        ingredient_service.merge_ingredients(session, keep=keep, remove=remove)

    with session_scope(session_factory) as session:
        assert session.get(Ingredient, remove_id) is None
        keep = session.get(Ingredient, keep_id)
        alias_names = {a.alias for a in keep.aliases}
        assert "Zwiebeln" in alias_names

        recipe = session.get(Recipe, recipe_id)
        assert recipe.ingredients[0].ingredient_id == keep_id
        assert keep.prices[0].price_per_unit == Decimal("1.50")

        shopping_list = session.get(ShoppingList, shopping_list_id)
        assert shopping_list.items[0].ingredient_id == keep_id


def test_merge_ingredients_handles_chained_merges_in_one_session(session_factory) -> None:
    """Regression: A->B then B->C in the same session must not fail on the alias created by A->B."""
    with session_scope(session_factory) as session:
        a = Ingredient(name="Paprikagewuer", normalized_name="paprikagewuer")
        b = Ingredient(name="Paprikagewuerz", normalized_name="paprikagewuerz")
        c = Ingredient(name="Paprikagewuerze", normalized_name="paprikagewuerze")
        session.add_all([a, b, c])
        session.flush()
        a_id, b_id, c_id = a.id, b.id, c.id

    with session_scope(session_factory) as session:
        a = session.get(Ingredient, a_id)
        b = session.get(Ingredient, b_id)
        c = session.get(Ingredient, c_id)
        ingredient_service.merge_ingredients(session, keep=b, remove=a)
        ingredient_service.merge_ingredients(session, keep=c, remove=b)

    with session_scope(session_factory) as session:
        assert session.get(Ingredient, a_id) is None
        assert session.get(Ingredient, b_id) is None
        survivor = session.get(Ingredient, c_id)
        alias_names = {alias.alias for alias in survivor.aliases}
        assert alias_names == {"Paprikagewuer", "Paprikagewuerz"}


def test_merge_ingredients_rejects_self_merge(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Zwiebel", normalized_name="zwiebel")
        session.add(ingredient)
        session.flush()
        with pytest.raises(ValueError):
            ingredient_service.merge_ingredients(session, keep=ingredient, remove=ingredient)


def test_generate_unique_ingredient_name_avoids_collision(session_factory) -> None:
    with session_scope(session_factory) as session:
        assert ingredient_service.generate_unique_ingredient_name(session) == "Neue Zutat"
        ingredient_service.create_ingredient(session, name="Neue Zutat")

        second_name = ingredient_service.generate_unique_ingredient_name(session)
        assert second_name == "Neue Zutat 2"
        ingredient_service.create_ingredient(session, name=second_name)

        third_name = ingredient_service.generate_unique_ingredient_name(session)
        assert third_name == "Neue Zutat 3"


def test_delete_ingredient_removes_it_when_unused(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Ungenutzte Zutat", normalized_name="ungenutzte zutat")
        session.add(ingredient)
        session.flush()
        ingredient_id = ingredient.id

    with session_scope(session_factory) as session:
        ingredient = session.get(Ingredient, ingredient_id)
        ingredient_service.delete_ingredient(session, ingredient)

    with session_scope(session_factory) as session:
        assert session.get(Ingredient, ingredient_id) is None


def test_delete_ingredient_blocks_when_used_in_recipe(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Zwiebel", normalized_name="zwiebel", default_unit="kg")
        session.add_all([recipe, ingredient])
        session.flush()
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("0.100"), unit="kg", price_unit="kg", sort_order=1)
        )
        session.flush()
        ingredient_id = ingredient.id

    with session_scope(session_factory) as session:
        ingredient = session.get(Ingredient, ingredient_id)
        with pytest.raises(ValueError, match="Testgericht"):
            ingredient_service.delete_ingredient(session, ingredient)

    with session_scope(session_factory) as session:
        assert session.get(Ingredient, ingredient_id) is not None
