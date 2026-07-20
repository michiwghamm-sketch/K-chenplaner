from datetime import date
from decimal import Decimal

import pytest

from app.db import session_scope
from app.models import CampYear, MealPlanEntry, Recipe
from app.services import feedback_service


@pytest.mark.parametrize(
    ("planned", "cooked", "expected"),
    [
        (20, 18, Decimal("0.900")),
        (10, 12, Decimal("1.200")),
        (0, 10, None),
        (10, None, None),
    ],
)
def test_calculate_quantity_factor(planned, cooked, expected) -> None:
    assert feedback_service.calculate_quantity_factor(planned, cooked) == expected


def test_record_feedback_computes_quantity_factor_and_validates_rating(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Kaiserschmarrn", normalized_name="kaiserschmarrn", default_portions=20)
        session.add_all([camp_year, recipe])
        session.flush()

        feedback = feedback_service.record_feedback(
            session,
            camp_year=camp_year,
            recipe=recipe,
            rating=4,
            planned_portions=20,
            cooked_portions=25,
        )
        assert feedback.quantity_factor_next_time == Decimal("1.250")

        with pytest.raises(ValueError):
            feedback_service.record_feedback(session, camp_year=camp_year, recipe=recipe, rating=6)


def test_recipe_feedback_history_orders_by_year_descending(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Gnocchi Salat", normalized_name="gnocchi salat", default_portions=20)
        session.add(recipe)
        for year in (2024, 2026, 2025):
            camp_year = CampYear(year=year, name=f"Zeltlager {year}")
            session.add(camp_year)
            session.flush()
            feedback_service.record_feedback(session, camp_year=camp_year, recipe=recipe, rating=3)
        session.flush()

        history = feedback_service.recipe_feedback_history(recipe)
        assert [entry.camp_year.year for entry in history] == [2026, 2025, 2024]


def test_list_feedback_candidates_excludes_cancelled_and_recipe_less_entries(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026", start_date=date(2026, 8, 1))
        recipe = Recipe(name="Chili con Carne", normalized_name="chili con carne")
        session.add_all([camp_year, recipe])
        session.flush()
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(meal_date=date(2026, 8, 2), meal_type="Abendessen", recipe=recipe, status="geplant"),
                MealPlanEntry(meal_date=date(2026, 8, 1), meal_type="Mittagessen", recipe=recipe, status="abgesagt"),
                MealPlanEntry(meal_date=date(2026, 8, 3), meal_type="Mittagessen", recipe=None, status="geplant"),
            ]
        )
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        candidates = feedback_service.list_feedback_candidates(session, camp_year)
        assert len(candidates) == 1
        assert candidates[0].meal_date == date(2026, 8, 2)


def test_save_meal_feedback_creates_one_feedback_per_meal_slot(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Spaghetti Bolognese", normalized_name="spaghetti bolognese")
        session.add_all([camp_year, recipe])
        session.flush()
        entry = MealPlanEntry(
            camp_year=camp_year,
            meal_date=date(2026, 8, 2),
            meal_type="Abendessen",
            recipe=recipe,
            planned_portions=95,
            status="geplant",
        )
        session.add(entry)
        session.flush()
        entry_id = entry.id

    with session_scope(session_factory) as session:
        entry = session.get(MealPlanEntry, entry_id)
        feedback_service.save_meal_feedback(
            session,
            entry,
            rating=4,
            quantity_sufficient="Ja, hat gereicht",
            cooked_portions=100,
            leftover_quantity=Decimal("1.500"),
            leftover_unit="kg",
            what_went_well="Lief gut",
        )

    with session_scope(session_factory) as session:
        entry = session.get(MealPlanEntry, entry_id)
        assert entry.feedback is not None
        assert entry.feedback.rating == 4
        assert entry.feedback.quantity_sufficient == "Ja, hat gereicht"
        assert entry.feedback.planned_portions == 95
        assert entry.feedback.quantity_factor_next_time == Decimal("1.053")

        # Erneutes Speichern fuer dieselbe Mahlzeit aktualisiert das bestehende Feedback statt ein zweites anzulegen.
        feedback_service.save_meal_feedback(session, entry, rating=5, cooked_portions=100)

    with session_scope(session_factory) as session:
        entry = session.get(MealPlanEntry, entry_id)
        assert entry.feedback.rating == 5


def test_save_meal_feedback_rejects_invalid_rating(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Ratatouille", normalized_name="ratatouille")
        session.add_all([camp_year, recipe])
        session.flush()
        entry = MealPlanEntry(camp_year=camp_year, meal_type="Mittagessen", recipe=recipe, status="geplant")
        session.add(entry)
        session.flush()

        with pytest.raises(ValueError):
            feedback_service.save_meal_feedback(session, entry, rating=7)
