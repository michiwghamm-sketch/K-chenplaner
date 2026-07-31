from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import CampYear, Ingredient, IngredientPrice, MealPlanEntry, Recipe, RecipeFeedback, RecipeIngredient
from app.services import planning_service


def test_create_camp_year_rejects_duplicate_year(session_factory) -> None:
    with session_scope(session_factory) as session:
        planning_service.create_camp_year(session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 3))

    with session_scope(session_factory) as session:
        with pytest.raises(ValueError):
            planning_service.create_camp_year(session, year=2026)


def test_update_camp_year_sets_dates_without_changing_year(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(session, year=2026)
        assert camp_year.start_date is None

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        planning_service.update_camp_year(
            session, camp_year, start_date=date(2026, 8, 1), end_date=date(2026, 8, 9), notes="Testnotiz"
        )

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        assert camp_year.start_date == date(2026, 8, 1)
        assert camp_year.end_date == date(2026, 8, 9)
        assert camp_year.notes == "Testnotiz"
        assert camp_year.year == 2026


def test_update_camp_year_rejects_rename_to_existing_year(session_factory) -> None:
    with session_scope(session_factory) as session:
        planning_service.create_camp_year(session, year=2025)
        planning_service.create_camp_year(session, year=2026)

    with session_scope(session_factory) as session:
        camp_year_2026 = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        with pytest.raises(ValueError):
            planning_service.update_camp_year(session, camp_year_2026, year=2025)


def test_update_camp_year_recomputes_participant_total(session_factory) -> None:
    with session_scope(session_factory) as session:
        planning_service.create_camp_year(
            session, year=2026, participant_count_children=10, participant_count_adults=2
        )

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        assert camp_year.participant_count_total == 12
        planning_service.update_camp_year(session, camp_year, participant_count_children=15)

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        assert camp_year.participant_count_total == 17


def test_days_until_start(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 10), end_date=date(2026, 8, 15)
        )
        assert planning_service.days_until_start(camp_year, today=date(2026, 8, 1)) == 9
        assert planning_service.days_until_start(camp_year, today=date(2026, 8, 20)) == -10

        no_dates_camp_year = planning_service.create_camp_year(session, year=2027)
        assert planning_service.days_until_start(no_dates_camp_year) is None


def test_meal_plan_completeness_ignores_cancelled_and_no_meal_entries(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Nudeln", normalized_name="nudeln")
        camp_year = planning_service.create_camp_year(session, year=2026)
        session.add(recipe)
        session.flush()
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(meal_type="Mittagessen", recipe=recipe, status="geplant"),
                MealPlanEntry(meal_type="Abendessen", recipe=None, status="geplant"),
                MealPlanEntry(meal_type="Frühstück", recipe=None, status="abgesagt"),
                MealPlanEntry(meal_type="Brotzeit", recipe=None, status="keine Mahlzeit"),
            ]
        )
        filled, total = planning_service.meal_plan_completeness(camp_year)
        assert (filled, total) == (1, 2)


def test_is_active_status() -> None:
    assert planning_service.is_active_status("geplant") is True
    assert planning_service.is_active_status(None) is True
    assert planning_service.is_active_status("abgesagt") is False
    assert planning_service.is_active_status(planning_service.NO_MEAL_STATUS) is False


def test_create_camp_year_stores_diet_breakdown_per_group(session_factory) -> None:
    with session_scope(session_factory) as session:
        planning_service.create_camp_year(
            session,
            year=2026,
            participant_count_children=30,
            participant_count_children_vegetarian=10,
            participant_count_children_meat=20,
            participant_count_adults=10,
            participant_count_adults_vegetarian=4,
            participant_count_adults_meat=6,
        )

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        assert camp_year.participant_count_children_vegetarian == 10
        assert camp_year.participant_count_children_meat == 20
        assert camp_year.participant_count_adults_vegetarian == 4
        assert camp_year.participant_count_adults_meat == 6
        # Die Gesamtzahl bleibt weiterhin nur aus Kinder/Erwachsene abgeleitet.
        assert camp_year.participant_count_total == 40


def test_generate_daily_meal_slots_creates_one_entry_per_day_and_meal_type(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 3)
        )
        created = planning_service.generate_daily_meal_slots(session, camp_year)
        # 3 days * 3 default meal types = 9 slots
        assert len(created) == 9
        assert created[0].weekday == planning_service.weekday_name(date(2026, 8, 1))

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        assert len(camp_year.meal_plan_entries) == 9
        assert len(camp_year.camp_days) == 3
        assert {day.day_date for day in camp_year.camp_days} == {
            date(2026, 8, 1),
            date(2026, 8, 2),
            date(2026, 8, 3),
        }


def test_generate_daily_meal_slots_is_idempotent(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        planning_service.generate_daily_meal_slots(session, camp_year)
        second_run = planning_service.generate_daily_meal_slots(session, camp_year)
        assert second_run == []
        assert len(camp_year.meal_plan_entries) == 3
        assert len(camp_year.camp_days) == 1


def test_set_status_validates_allowed_values(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        entries = planning_service.generate_daily_meal_slots(session, camp_year)
        planning_service.set_status(entries[0], "bestellt")
        assert entries[0].status == "bestellt"
        with pytest.raises(ValueError):
            planning_service.set_status(entries[0], "erledigt")


def test_derive_shopping_date_subtracts_days() -> None:
    assert planning_service.derive_shopping_date(date(2026, 8, 5), days_before=2) == date(2026, 8, 3)


def test_camp_day_range_lists_all_days_inclusive(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 3)
        )
        assert planning_service.camp_day_range(camp_year) == [
            date(2026, 8, 1),
            date(2026, 8, 2),
            date(2026, 8, 3),
        ]


def test_camp_day_range_empty_without_dates(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(session, year=2026)
        assert planning_service.camp_day_range(camp_year) == []


def test_get_or_create_camp_day_is_idempotent(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        first = planning_service.get_or_create_camp_day(session, camp_year, date(2026, 8, 1))
        second = planning_service.get_or_create_camp_day(session, camp_year, date(2026, 8, 1))
        assert first.id == second.id
        assert first.weekday == planning_service.weekday_name(date(2026, 8, 1))

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        assert len(camp_year.camp_days) == 1


def test_set_day_responsible_updates_person_and_notes(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        camp_day = planning_service.get_or_create_camp_day(session, camp_year, date(2026, 8, 1))
        planning_service.set_day_responsible(camp_day, responsible_person="Hias", notes="Vertretung ab 14 Uhr")
        assert camp_day.responsible_person == "Hias"
        assert camp_day.notes == "Vertretung ab 14 Uhr"


def test_get_or_create_meal_entry_reuses_existing_entry(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        planning_service.generate_daily_meal_slots(session, camp_year)
        first = planning_service.get_or_create_meal_entry(session, camp_year, date(2026, 8, 1), "Frühstück")
        second = planning_service.get_or_create_meal_entry(session, camp_year, date(2026, 8, 1), "Frühstück")
        assert first.id == second.id

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        # 3 default meal types already generated - get_or_create must not add a duplicate.
        matching = [e for e in camp_year.meal_plan_entries if e.meal_type == "Frühstück"]
        assert len(matching) == 1


def test_get_or_create_meal_entry_creates_missing_slot(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        entry = planning_service.get_or_create_meal_entry(session, camp_year, date(2026, 8, 1), "Brotzeit")
        assert isinstance(entry, MealPlanEntry)
        assert entry.status == "geplant"


def _priced_recipe(session, name: str, *, price: Decimal) -> Recipe:
    recipe = Recipe(name=name, normalized_name=name.lower(), default_portions=10)
    ingredient = Ingredient(name=f"{name} Zutat", normalized_name=f"{name.lower()} zutat", default_unit="kg")
    ingredient.prices.append(IngredientPrice(price_per_unit=price, unit="kg", year=2026))
    session.add_all([recipe, ingredient])
    session.flush()
    recipe.ingredients.append(
        RecipeIngredient(ingredient=ingredient, quantity=Decimal("1.000"), unit="kg", price_unit="kg", sort_order=1)
    )
    return recipe


def test_add_meal_entry_allows_multiple_dishes_per_slot(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        meat = Recipe(name="Braten", normalized_name="braten")
        veggi = Recipe(name="Gemüsecurry", normalized_name="gemuesecurry")
        session.add_all([meat, veggi])
        session.flush()

        planning_service.add_meal_entry(
            session, camp_year, date(2026, 8, 1), "Mittagessen", recipe=meat, planned_portions=30
        )
        planning_service.add_meal_entry(
            session, camp_year, date(2026, 8, 1), "Mittagessen", recipe=veggi, planned_portions=10
        )

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        dishes = planning_service.meal_entries_for_slot(camp_year, date(2026, 8, 1), "Mittagessen")
        assert [d.recipe.name for d in dishes] == ["Braten", "Gemüsecurry"]


def test_delete_meal_entry_removes_it_when_no_feedback(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        session.add(recipe)
        session.flush()
        entry = planning_service.add_meal_entry(session, camp_year, date(2026, 8, 1), "Mittagessen", recipe=recipe)
        entry_id = entry.id

    with session_scope(session_factory) as session:
        entry = session.get(MealPlanEntry, entry_id)
        planning_service.delete_meal_entry(session, entry)

    with session_scope(session_factory) as session:
        assert session.get(MealPlanEntry, entry_id) is None


def test_delete_meal_entry_succeeds_even_when_recipe_has_feedback(session_factory) -> None:
    """Feedback haengt seit der (Camp-Jahr, Rezept)-Umstellung nicht mehr an einem einzelnen Slot -
    das Loeschen eines Slots darf ein bestehendes Feedback also nicht mehr blockieren."""
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        session.add(recipe)
        session.flush()
        entry = planning_service.add_meal_entry(session, camp_year, date(2026, 8, 1), "Mittagessen", recipe=recipe)
        session.add(RecipeFeedback(camp_year=camp_year, recipe=recipe))
        entry_id = entry.id

    with session_scope(session_factory) as session:
        entry = session.get(MealPlanEntry, entry_id)
        planning_service.delete_meal_entry(session, entry)

    with session_scope(session_factory) as session:
        assert session.get(MealPlanEntry, entry_id) is None


def test_day_summary_sums_portions_and_cost_across_dishes(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        meat = _priced_recipe(session, "Braten", price=Decimal("2.00"))
        veggi = _priced_recipe(session, "Gemuesecurry", price=Decimal("1.00"))
        session.flush()

        planning_service.add_meal_entry(session, camp_year, date(2026, 8, 1), "Mittagessen", recipe=meat, planned_portions=10)
        planning_service.add_meal_entry(session, camp_year, date(2026, 8, 1), "Mittagessen", recipe=veggi, planned_portions=5)
        # Abgesagte Gerichte zaehlen nicht in die Auswertung.
        cancelled = planning_service.add_meal_entry(
            session, camp_year, date(2026, 8, 1), "Abendessen", recipe=meat, planned_portions=999
        )
        planning_service.set_status(cancelled, "abgesagt")

    with session_scope(session_factory) as session:
        camp_year = session.execute(select(CampYear).where(CampYear.year == 2026)).scalar_one()
        summary = planning_service.day_summary(session, camp_year, date(2026, 8, 1))
        assert summary.total_portions == 15
        assert summary.total_cost == Decimal("25.00")
        assert len(summary.meals) == 2
        assert summary.has_missing_prices is False
