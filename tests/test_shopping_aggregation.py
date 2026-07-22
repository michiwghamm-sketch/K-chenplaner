from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.db import session_scope
from app.models import CampYear, Ingredient, IngredientPrice, MealPlanEntry, Recipe, RecipeIngredient, ShoppingList, ShoppingListItem
from app.services import shopping_service


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


def test_generate_shopping_list_aggregates_quantities_across_meals(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg", category="Trockenware")
        ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("2.00"), unit="kg", year=2026))

        recipe = Recipe(name="Spaghetti Napoli", normalized_name="spaghetti napoli", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("0.100"), unit="kg", price_unit="kg", sort_order=1)
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(
                    meal_date=date(2026, 8, 2),
                    meal_type="Mittagessen",
                    recipe=recipe,
                    planned_portions=20,
                    status="geplant",
                    shopping_date=date(2026, 8, 1),
                ),
                MealPlanEntry(
                    meal_date=date(2026, 8, 4),
                    meal_type="Mittagessen",
                    recipe=recipe,
                    planned_portions=10,
                    status="geplant",
                    shopping_date=date(2026, 8, 3),
                ),
                MealPlanEntry(
                    meal_date=date(2026, 8, 6),
                    meal_type="Mittagessen",
                    recipe=recipe,
                    planned_portions=999,
                    status="abgesagt",
                ),
            ]
        )
        session.add(camp_year)
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        shopping_list = shopping_service.generate_shopping_list(session, camp_year)

        assert len(shopping_list.items) == 1
        item = shopping_list.items[0]
        # (20 + 10) portions * 0.100kg / 10 base portions = 0.300 kg total, cancelled meal excluded.
        assert item.quantity == Decimal("0.300")
        assert item.estimated_total_price == Decimal("0.60")
        assert item.category == "Trockenware"
        assert item.needed_date == date(2026, 8, 2)
        assert item.shopping_date == date(2026, 8, 1)
        assert item.status == "offen"


def test_generate_shopping_list_total_list_skips_shopping_dates_but_keeps_needed_date(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg")

        recipe = Recipe(name="Spaghetti Napoli", normalized_name="spaghetti napoli", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("0.100"), unit="kg", price_unit="kg", sort_order=1)
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026", start_date=date(2026, 8, 1), end_date=date(2026, 8, 10))
        camp_year.meal_plan_entries.append(
            MealPlanEntry(
                meal_date=date(2026, 8, 5),
                meal_type="Mittagessen",
                recipe=recipe,
                planned_portions=10,
                status="geplant",
            )
        )
        session.add(camp_year)
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        shopping_list = shopping_service.generate_shopping_list(session, camp_year, assign_shopping_dates=False)

        assert len(shopping_list.items) == 1
        item = shopping_list.items[0]
        assert item.needed_date == date(2026, 8, 5)
        assert item.shopping_date is None


def test_format_date_de() -> None:
    assert shopping_service.format_date_de(None) == ""
    assert shopping_service.format_date_de(date(2026, 8, 5)) == "05.08.2026"


def test_generate_shopping_list_derives_shopping_date_one_day_before_meal(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Frische Milch", normalized_name="frische milch", default_unit="l")

        recipe = Recipe(name="Kaiserschmarrn", normalized_name="kaiserschmarrn", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="l", price_unit="l", sort_order=1)
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026", start_date=date(2026, 8, 1), end_date=date(2026, 8, 10))
        camp_year.meal_plan_entries.append(
            MealPlanEntry(meal_date=date(2026, 8, 5), meal_type="Fruehstueck", recipe=recipe, planned_portions=10, status="geplant")
        )
        session.add(camp_year)
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        shopping_list = shopping_service.generate_shopping_list(session, camp_year)

        assert len(shopping_list.items) == 1
        assert shopping_list.items[0].shopping_date == date(2026, 8, 4)


def test_generate_shopping_list_consolidates_shelf_stable_ingredients_to_camp_start(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg", storage_type="Trockenware")

        recipe = Recipe(name="Spaghetti Napoli", normalized_name="spaghetti napoli", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg", price_unit="kg", sort_order=1)
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026", start_date=date(2026, 8, 1), end_date=date(2026, 8, 10))
        camp_year.meal_plan_entries.append(
            MealPlanEntry(meal_date=date(2026, 8, 8), meal_type="Mittagessen", recipe=recipe, planned_portions=10, status="geplant")
        )
        session.add(camp_year)
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        shopping_list = shopping_service.generate_shopping_list(session, camp_year)

        assert len(shopping_list.items) == 1
        # Lagerfaehig -> ein Rutsch zu Lagerbeginn statt kurz vor der einzelnen Mahlzeit.
        assert shopping_list.items[0].shopping_date == date(2026, 7, 31)


def test_generate_shopping_list_respects_manual_shopping_date_override(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg", storage_type="Trockenware")

        recipe = Recipe(name="Spaghetti Napoli", normalized_name="spaghetti napoli", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg", price_unit="kg", sort_order=1)
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026", start_date=date(2026, 8, 1), end_date=date(2026, 8, 10))
        camp_year.meal_plan_entries.append(
            MealPlanEntry(
                meal_date=date(2026, 8, 8),
                meal_type="Mittagessen",
                recipe=recipe,
                planned_portions=10,
                status="geplant",
                shopping_date=date(2026, 8, 6),
            )
        )
        session.add(camp_year)
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        shopping_list = shopping_service.generate_shopping_list(session, camp_year)

        assert len(shopping_list.items) == 1
        assert shopping_list.items[0].shopping_date == date(2026, 8, 6)


def test_group_by_shopping_day_and_total_cost(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        shopping_list.items.extend(
            [
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", estimated_total_price=Decimal("1.50"), shopping_date=date(2026, 8, 1)),
                ShoppingListItem(quantity=Decimal("2.000"), unit="kg", estimated_total_price=Decimal("3.00"), shopping_date=date(2026, 8, 1)),
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", estimated_total_price=Decimal("2.00"), shopping_date=date(2026, 8, 3)),
            ]
        )
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id = shopping_list.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        groups = shopping_service.group_by_shopping_day(shopping_list)
        assert len(groups[date(2026, 8, 1)]) == 2
        assert shopping_service.total_estimated_cost(shopping_list) == Decimal("6.50")


def test_grouped_by_day_ordered_sorts_ascending_with_none_last(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        shopping_list.items.extend(
            [
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", shopping_date=date(2026, 8, 3)),
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", shopping_date=date(2026, 8, 1)),
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", shopping_date=None),
            ]
        )
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id = shopping_list.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        ordered = shopping_service.grouped_by_day_ordered(shopping_list)
        assert [day for day, _ in ordered] == [date(2026, 8, 1), date(2026, 8, 3), None]


def test_grouped_by_store_ordered_sorts_alphabetically_with_none_last(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        shopping_list.items.extend(
            [
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", store="Rewe"),
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", store="Aldi"),
                ShoppingListItem(quantity=Decimal("1.000"), unit="kg", store=None),
            ]
        )
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id = shopping_list.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        ordered = shopping_service.grouped_by_store_ordered(shopping_list)
        assert [store for store, _ in ordered] == ["Aldi", "Rewe", None]


def test_set_item_store_normalizes_blank_to_none(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        shopping_list.items.append(ShoppingListItem(quantity=Decimal("1.000"), unit="kg"))
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        item_id = shopping_list.items[0].id

    with session_scope(session_factory) as session:
        item = session.get(ShoppingListItem, item_id)
        shopping_service.set_item_store(item, "  Edeka  ")
        assert item.store == "Edeka"
        shopping_service.set_item_store(item, "   ")
        assert item.store is None


def test_format_shopping_day_label() -> None:
    assert shopping_service.format_shopping_day_label(None) == "Ohne Einkaufstag"
    assert shopping_service.format_shopping_day_label(date(2026, 8, 3)) == "Montag, 03.08.2026"


def test_delete_shopping_list_removes_list_and_items(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        shopping_list.items.append(ShoppingListItem(quantity=Decimal("1.000"), unit="kg"))
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id = shopping_list.id
        item_id = shopping_list.items[0].id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        shopping_service.delete_shopping_list(session, shopping_list)

    with session_scope(session_factory) as session:
        assert session.get(ShoppingList, shopping_list_id) is None
        assert session.get(ShoppingListItem, item_id) is None
