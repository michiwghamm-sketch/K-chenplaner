from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import (
    CampYear,
    Ingredient,
    IngredientPrice,
    MealPlanEntry,
    Recipe,
    RecipeIngredient,
    ShoppingList,
    ShoppingListItem,
    ShoppingListItemAllocation,
    ShoppingTrip,
)
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
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg")
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

        assert len(shopping_list.items) == 2
        items_by_day = {item.shopping_date: item for item in shopping_list.items}
        item = items_by_day[date(2026, 8, 1)]
        assert item.quantity == Decimal("2.000")
        assert item.estimated_total_price == Decimal("4.00")
        assert item.needed_date == date(2026, 8, 2)
        assert item.status == "offen"
        assert items_by_day[date(2026, 8, 3)].quantity == Decimal("1.000")
        assert items_by_day[date(2026, 8, 3)].estimated_total_price == Decimal("2.00")


def test_generate_shopping_list_scales_plan_portions_and_converts_price_unit(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Mehl", normalized_name="mehl", default_unit="kg")
        ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("2.00"), unit="kg", year=2026))

        recipe = Recipe(name="Pfannkuchen", normalized_name="pfannkuchen", default_portions=10)
        recipe.ingredients.append(
            RecipeIngredient(ingredient=ingredient, quantity=Decimal("100.000"), unit="g", price_unit="g", sort_order=1)
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        camp_year.meal_plan_entries.append(
            MealPlanEntry(
                meal_date=date(2026, 8, 2),
                meal_type="Mittagessen",
                recipe=recipe,
                planned_portions=30,
                status="geplant",
            )
        )
        session.add(camp_year)
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        shopping_list = shopping_service.generate_shopping_list(session, camp_year)

        assert len(shopping_list.items) == 1
        item = shopping_list.items[0]
        assert item.quantity == Decimal("3.000")
        assert item.unit == "kg"
        assert item.estimated_price_per_unit == Decimal("2.0000")
        assert item.estimated_total_price == Decimal("6.00")


def test_generate_shopping_list_merges_convertible_units_to_ingredient_default_unit(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Milch", normalized_name="milch", default_unit="l")
        ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("1.50"), unit="l", year=2026))

        recipe = Recipe(name="Fruehstueck Kinder", normalized_name="fruehstueck kinder", default_portions=100)
        recipe.ingredients.extend(
            [
                RecipeIngredient(ingredient=ingredient, quantity=Decimal("500.000"), unit="ml", price_unit="ml", sort_order=1),
                RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="l", price_unit="l", sort_order=2),
            ]
        )

        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(meal_date=date(2026, 8, 2), meal_type="Fruehstueck", recipe=recipe, planned_portions=100, status="geplant"),
                MealPlanEntry(meal_date=date(2026, 8, 3), meal_type="Fruehstueck", recipe=recipe, planned_portions=100, status="geplant"),
            ]
        )
        session.add(camp_year)
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        shopping_list = shopping_service.generate_shopping_list(session, camp_year, assign_shopping_dates=False)

        assert len(shopping_list.items) == 1
        item = shopping_list.items[0]
        assert item.quantity == Decimal("300.000")
        assert item.unit == "l"
        assert item.estimated_total_price == Decimal("450.00")


def test_generate_shopping_list_uses_recipe_quantity_as_per_portion_amount(session_factory) -> None:
    with session_scope(session_factory) as session:
        bread = Ingredient(name="Brot", normalized_name="brot", default_unit="€/kg")
        bread.prices.append(IngredientPrice(price_per_unit=Decimal("3.98"), unit="kg", year=2026))
        children = Recipe(name="Fruehstueck Kinder", normalized_name="fruehstueck kinder", default_portions=186)
        children.ingredients.append(
            RecipeIngredient(ingredient=bread, quantity=Decimal("0.070"), unit="kg", price_unit="kg", sort_order=1)
        )
        adults = Recipe(name="Fruehstueck Betreuer", normalized_name="fruehstueck betreuer", default_portions=69)
        adults.ingredients.append(
            RecipeIngredient(ingredient=bread, quantity=Decimal("0.250"), unit="kg", price_unit="kg", sort_order=1)
        )
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        camp_year.meal_plan_entries.append(
            MealPlanEntry(meal_date=date(2026, 8, 9), meal_type="Fruehstueck", recipe=adults, planned_portions=24, status="geplant")
        )
        for day in range(10, 16):
            camp_year.meal_plan_entries.append(
                MealPlanEntry(
                    meal_date=date(2026, 8, day),
                    meal_type="Fruehstueck",
                    recipe=children,
                    planned_portions=100,
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
        assert item.quantity == Decimal("48.000")
        assert item.unit == "kg"
        assert item.estimated_total_price == Decimal("191.04")


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


def test_generate_shopping_list_respects_manual_shopping_date_override(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg")

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


def test_grouped_by_store_ordered_allocations_sorts_alphabetically(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        karotten = Ingredient(name="Karotten", normalized_name="karotten", default_unit="kg")
        zwiebeln = Ingredient(name="Zwiebeln", normalized_name="zwiebeln", default_unit="kg")
        session.add_all([karotten, zwiebeln])
        session.flush()
        item_a = ShoppingListItem(ingredient=karotten, quantity=Decimal("1.000"), unit="kg")
        item_b = ShoppingListItem(ingredient=zwiebeln, quantity=Decimal("1.000"), unit="kg")
        shopping_list.items.extend([item_a, item_b])
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        rewe_trip = shopping_service.create_shopping_trip(
            session, shopping_list, store="Rewe", participants=[], selections=[(karotten.id, "kg", Decimal("1.000"))]
        )
        aldi_trip = shopping_service.create_shopping_trip(
            session, shopping_list, store="Aldi", participants=[], selections=[(zwiebeln.id, "kg", Decimal("1.000"))]
        )
        assert rewe_trip.store == "Rewe" and aldi_trip.store == "Aldi"
        shopping_list_id = shopping_list.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        ordered = shopping_service.grouped_by_store_ordered_allocations(shopping_list)
        assert [store for store, _ in ordered] == ["Aldi", "Rewe"]


def test_create_shopping_trip_rejects_quantity_over_remaining(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        karotten = Ingredient(name="Karotten", normalized_name="karotten", default_unit="kg")
        item = ShoppingListItem(ingredient=karotten, quantity=Decimal("30.000"), unit="kg")
        shopping_list.items.append(item)
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id, ingredient_id = shopping_list.id, karotten.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        assert shopping_service.remaining_quantity_for_ingredient(shopping_list, ingredient_id, "kg") == Decimal("30.000")

        trip = shopping_service.create_shopping_trip(
            session, shopping_list, store="Metro", participants=["Anna", "Ben"], selections=[(ingredient_id, "kg", Decimal("20.000"))]
        )
        assert shopping_service.remaining_quantity_for_ingredient(shopping_list, ingredient_id, "kg") == Decimal("10.000")
        # Eine Auswahl = ein Listeneintrag = eine Allocation, komplett an eine Person.
        assert len(trip.allocations) == 1
        assert trip.allocations[0].shopping_list_item_id == item.id
        assert trip.allocations[0].assigned_to in ("Anna", "Ben")

        with pytest.raises(ValueError):
            shopping_service.create_shopping_trip(
                session, shopping_list, store="Edeka", participants=[], selections=[(ingredient_id, "kg", Decimal("15.000"))]
            )


def test_items_available_for_planning_combines_ingredient_across_shopping_days(session_factory) -> None:
    """Regressionstest: der "Einkauf planen"-Assistent soll dieselbe Zutat, die an mehreren
    Einkaufstagen gebraucht wird, als EINE Gesamtmenge zeigen statt als mehrere Tages-Zeilen -
    und eine Auswahl daraus wird zu GENAU EINEM Listeneintrag, nicht auf mehrere Zeilen
    gesplittet (siehe ShoppingListItemAllocation-Docstring)."""
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        karotten = Ingredient(name="Karotten", normalized_name="karotten", default_unit="kg")
        session.add(karotten)
        session.flush()
        shopping_list.items.extend(
            [
                ShoppingListItem(ingredient=karotten, quantity=Decimal("18.000"), unit="kg", shopping_date=date(2026, 8, 1)),
                ShoppingListItem(ingredient=karotten, quantity=Decimal("12.000"), unit="kg", shopping_date=date(2026, 8, 3)),
            ]
        )
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id, ingredient_id = shopping_list.id, karotten.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        groups = shopping_service.items_available_for_planning(shopping_list)
        assert len(groups) == 1
        assert groups[0].ingredient_name == "Karotten"
        assert groups[0].remaining_quantity == Decimal("30.000")

        trip = shopping_service.create_shopping_trip(
            session, shopping_list, store="Metro", participants=[], selections=[(ingredient_id, "kg", Decimal("20.000"))]
        )
        assert len(trip.allocations) == 1
        assert trip.allocations[0].quantity == Decimal("20.000")
        assert shopping_service.remaining_quantity_for_ingredient(shopping_list, ingredient_id, "kg") == Decimal("10.000")


def test_migrate_legacy_store_status_creates_one_trip_per_store(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        karotten = Ingredient(name="Karotten", normalized_name="karotten", default_unit="kg")
        zwiebeln = Ingredient(name="Zwiebeln", normalized_name="zwiebeln", default_unit="kg")
        session.add_all([karotten, zwiebeln])
        session.flush()
        shopping_list.items.extend(
            [
                # Karotten an zwei Einkaufstagen - muss beim Migrieren zu EINER Allocation
                # zusammengefasst werden (Gesamtmenge, kein Splitten mehr).
                ShoppingListItem(ingredient=karotten, quantity=Decimal("1.000"), unit="kg", store="Rewe", status="gekauft"),
                ShoppingListItem(ingredient=karotten, quantity=Decimal("2.000"), unit="kg", store="Rewe", status="offen"),
                ShoppingListItem(ingredient=zwiebeln, quantity=Decimal("1.000"), unit="kg", store="Rewe"),
                ShoppingListItem(ingredient=karotten, quantity=Decimal("1.000"), unit="kg", store=None),
            ]
        )
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id = shopping_list.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        shopping_service.migrate_legacy_store_status(session, shopping_list)
        assert len(shopping_list.trips) == 1
        assert shopping_list.trips[0].store == "Rewe"
        # Karotten (zusammengefasst, 3 kg) + Zwiebeln (1 kg) = 2 Allocations.
        assert len(shopping_list.trips[0].allocations) == 2
        karotten_allocation = next(a for a in shopping_list.trips[0].allocations if a.ingredient_id == karotten.id)
        assert karotten_allocation.quantity == Decimal("3.000")

        # Idempotent: zweiter Aufruf legt nichts doppelt an.
        shopping_service.migrate_legacy_store_status(session, shopping_list)
        assert len(shopping_list.trips) == 1
        assert len(shopping_list.trips[0].allocations) == 2


def test_aggregated_items_sorted_combines_same_ingredient_and_sorts_alphabetically(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        zwiebeln = Ingredient(name="Zwiebeln", normalized_name="zwiebeln", default_unit="kg")
        kartoffeln = Ingredient(name="Kartoffeln", normalized_name="kartoffeln", default_unit="kg")
        session.add_all([zwiebeln, kartoffeln])
        session.flush()
        shopping_list.items.extend(
            [
                # Absichtlich nicht alphabetisch eingefuegt, und Kartoffeln zweimal (zwei
                # Einkaufstage) - genau das Szenario aus der ungruppierten PDF-Ansicht.
                ShoppingListItem(
                    ingredient=zwiebeln, quantity=Decimal("1.000"), unit="kg",
                    estimated_price_per_unit=Decimal("1.00"), estimated_total_price=Decimal("1.00"),
                    shopping_date=date(2026, 8, 1),
                ),
                ShoppingListItem(
                    ingredient=kartoffeln, quantity=Decimal("2.000"), unit="kg",
                    estimated_price_per_unit=Decimal("1.50"), estimated_total_price=Decimal("3.00"),
                    shopping_date=date(2026, 8, 1),
                ),
                ShoppingListItem(
                    ingredient=kartoffeln, quantity=Decimal("3.000"), unit="kg",
                    estimated_price_per_unit=Decimal("1.50"), estimated_total_price=Decimal("4.50"),
                    shopping_date=date(2026, 8, 3),
                ),
            ]
        )
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id = shopping_list.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        aggregated = shopping_service.aggregated_items_sorted(shopping_list)

        assert [row.ingredient_name for row in aggregated] == ["Kartoffeln", "Zwiebeln"]

        kartoffeln_row = aggregated[0]
        assert kartoffeln_row.quantity == Decimal("5.000")
        assert kartoffeln_row.estimated_total_price == Decimal("7.50")
        assert kartoffeln_row.has_missing_price is False


def test_aggregated_items_sorted_flags_missing_price_when_any_contributing_item_lacks_one(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        mehl = Ingredient(name="Mehl", normalized_name="mehl", default_unit="kg")
        session.add(mehl)
        session.flush()
        shopping_list.items.extend(
            [
                ShoppingListItem(
                    ingredient=mehl, quantity=Decimal("1.000"), unit="kg",
                    estimated_price_per_unit=Decimal("1.00"), estimated_total_price=Decimal("1.00"),
                    shopping_date=date(2026, 8, 1),
                ),
                ShoppingListItem(
                    ingredient=mehl, quantity=Decimal("2.000"), unit="kg",
                    estimated_price_per_unit=None, estimated_total_price=None,
                    shopping_date=date(2026, 8, 3),
                ),
            ]
        )
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        shopping_list_id = shopping_list.id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        aggregated = shopping_service.aggregated_items_sorted(shopping_list)

        assert len(aggregated) == 1
        assert aggregated[0].quantity == Decimal("3.000")
        assert aggregated[0].estimated_total_price is None
        assert aggregated[0].has_missing_price is True


def test_set_allocation_assigned_to_normalizes_blank_to_none(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        mehl = Ingredient(name="Mehl", normalized_name="mehl", default_unit="kg")
        session.add(mehl)
        session.flush()
        item = ShoppingListItem(ingredient=mehl, quantity=Decimal("1.000"), unit="kg")
        shopping_list.items.append(item)
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        trip = shopping_service.create_shopping_trip(
            session, shopping_list, store="Edeka", participants=[], selections=[(mehl.id, "kg", Decimal("1.000"))]
        )
        allocation_id = trip.allocations[0].id

    with session_scope(session_factory) as session:
        allocation = session.get(ShoppingListItemAllocation, allocation_id)
        shopping_service.set_allocation_assigned_to(allocation, "  Anna  ")
        assert allocation.assigned_to == "Anna"
        shopping_service.set_allocation_assigned_to(allocation, "   ")
        assert allocation.assigned_to is None


def test_reshuffle_trip_assignments_updates_participants(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        ingredients = [
            Ingredient(name=name, normalized_name=name.lower(), default_unit="kg")
            for name in ("Karotten", "Zwiebeln", "Kartoffeln", "Sellerie")
        ]
        session.add_all(ingredients)
        session.flush()
        items = [ShoppingListItem(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg") for ingredient in ingredients]
        shopping_list.items.extend(items)
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()
        trip = shopping_service.create_shopping_trip(
            session,
            shopping_list,
            store="Metro",
            participants=["Anna"],
            selections=[(ingredient.id, "kg", Decimal("1.000")) for ingredient in ingredients],
        )
        assert all(allocation.assigned_to == "Anna" for allocation in trip.allocations)
        trip_id = trip.id

    with session_scope(session_factory) as session:
        trip = session.get(ShoppingTrip, trip_id)
        shopping_service.reshuffle_trip_assignments(trip, ["Ben", "Chris"])
        assigned = {allocation.assigned_to for allocation in trip.allocations}
        assert assigned == {"Ben", "Chris"}
        assert trip.participants_text == "Ben, Chris"


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


def test_delete_shopping_list_removes_planned_trips_and_allocations(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        shopping_list = ShoppingList(name="Einkaufsliste", camp_year=camp_year)
        ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg")
        session.add(ingredient)
        session.flush()
        shopping_list.items.append(ShoppingListItem(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg"))
        session.add(camp_year)
        session.add(shopping_list)
        session.flush()

        trip = shopping_service.create_shopping_trip(
            session,
            shopping_list,
            store="Metro",
            participants=["Anna"],
            selections=[(ingredient.id, "kg", Decimal("1.000"))],
        )
        shopping_list_id = shopping_list.id
        item_id = shopping_list.items[0].id
        trip_id = trip.id
        allocation_id = trip.allocations[0].id

    with session_scope(session_factory) as session:
        shopping_list = session.get(ShoppingList, shopping_list_id)
        shopping_service.delete_shopping_list(session, shopping_list)

    with session_scope(session_factory) as session:
        assert session.get(ShoppingList, shopping_list_id) is None
        assert session.get(ShoppingListItem, item_id) is None
        assert session.get(ShoppingTrip, trip_id) is None
        assert session.get(ShoppingListItemAllocation, allocation_id) is None
