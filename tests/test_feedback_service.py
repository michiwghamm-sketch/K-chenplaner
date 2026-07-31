from datetime import date
from decimal import Decimal

import pytest

from app.db import session_scope
from app.models import CampYear, MealPlanEntry, Recipe, RecipeFeedback
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
        assert candidates[0].recipe_name == "Chili con Carne"
        assert candidates[0].occurrence_count == 1
        assert candidates[0].first_date == date(2026, 8, 2)


def test_list_feedback_candidates_groups_repeated_recipe_into_one_candidate(session_factory) -> None:
    """Ein Rezept, das mehrfach im Wochenplan steht (z. B. Fruehstueck an 5 Tagen), soll trotzdem
    nur ein Feedback-Kandidat sein, nicht einer je Slot."""
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Müsli", normalized_name="müsli")
        session.add_all([camp_year, recipe])
        session.flush()
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(meal_date=date(2026, 8, d), meal_type="Frühstück", recipe=recipe, planned_portions=20, status="geplant")
                for d in (1, 2, 3)
            ]
        )
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        candidates = feedback_service.list_feedback_candidates(session, camp_year)
        assert len(candidates) == 1
        assert candidates[0].occurrence_count == 3
        assert candidates[0].total_planned_portions == 60


def test_list_feedback_candidates_sums_expected_attendees_from_target_group(session_factory) -> None:
    """Anwesenden-Referenz je Kandidat: aus der Zielgruppe je Slot (Kinder/Betreuer/Alle) und den
    Teilnehmerzahlen des Camp-Jahrs abgeleitet, ueber alle Vorkommen aufsummiert."""
    with session_scope(session_factory) as session:
        camp_year = CampYear(
            year=2026,
            name="Zeltlager 2026",
            participant_count_children=20,
            participant_count_adults=5,
            participant_count_total=25,
        )
        recipe = Recipe(name="Müsli", normalized_name="müsli")
        session.add_all([camp_year, recipe])
        session.flush()
        camp_year.meal_plan_entries.extend(
            [
                MealPlanEntry(
                    meal_date=date(2026, 8, 1),
                    meal_type="Frühstück",
                    recipe=recipe,
                    planned_portions=20,
                    status="geplant",
                    target_group="Kinder",
                ),
                MealPlanEntry(
                    meal_date=date(2026, 8, 2),
                    meal_type="Frühstück",
                    recipe=recipe,
                    planned_portions=20,
                    status="geplant",
                    target_group="Kinder",
                ),
            ]
        )
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        candidates = feedback_service.list_feedback_candidates(session, camp_year)
        assert len(candidates) == 1
        assert candidates[0].expected_attendees_total == 40


def test_list_feedback_candidates_leaves_expected_attendees_none_without_data(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Müsli", normalized_name="müsli")
        session.add_all([camp_year, recipe])
        session.flush()
        camp_year.meal_plan_entries.append(
            MealPlanEntry(meal_date=date(2026, 8, 1), meal_type="Frühstück", recipe=recipe, status="geplant")
        )
        session.flush()
        camp_year_id = camp_year.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        candidates = feedback_service.list_feedback_candidates(session, camp_year)
        assert candidates[0].expected_attendees_total is None


def test_save_feedback_creates_one_feedback_per_recipe_and_year(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Spaghetti Bolognese", normalized_name="spaghetti bolognese")
        session.add_all([camp_year, recipe])
        session.flush()
        camp_year_id = camp_year.id
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, camp_year_id)
        recipe = session.get(Recipe, recipe_id)
        feedback_service.save_feedback(
            session,
            camp_year,
            recipe,
            rating=4,
            quantity_sufficient="Ja, hat gereicht",
            planned_portions=95,
            cooked_portions=100,
            leftover_quantity=Decimal("1.500"),
            leftover_unit="kg",
            what_went_well="Lief gut",
        )

    with session_scope(session_factory) as session:
        feedback = feedback_service.get_feedback(session, camp_year_id, recipe_id)
        assert feedback is not None
        assert feedback.rating == 4
        assert feedback.quantity_sufficient == "Ja, hat gereicht"
        assert feedback.planned_portions == 95
        assert feedback.quantity_factor_next_time == Decimal("1.053")

        # Erneutes Speichern fuer dasselbe Rezept/Jahr aktualisiert das bestehende Feedback statt
        # ein zweites anzulegen (verletzt sonst den Unique-Constraint camp_year_id/recipe_id).
        camp_year = session.get(CampYear, camp_year_id)
        recipe = session.get(Recipe, recipe_id)
        feedback_service.save_feedback(session, camp_year, recipe, rating=5, cooked_portions=100)

    with session_scope(session_factory) as session:
        feedback = feedback_service.get_feedback(session, camp_year_id, recipe_id)
        assert feedback.rating == 5


def test_save_feedback_rejects_invalid_rating(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Ratatouille", normalized_name="ratatouille")
        session.add_all([camp_year, recipe])
        session.flush()

        with pytest.raises(ValueError):
            feedback_service.save_feedback(session, camp_year, recipe, rating=7)


def test_delete_feedback_removes_entry(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = CampYear(year=2026, name="Zeltlager 2026")
        recipe = Recipe(name="Ratatouille", normalized_name="ratatouille")
        session.add_all([camp_year, recipe])
        session.flush()
        feedback = feedback_service.record_feedback(session, camp_year=camp_year, recipe=recipe, rating=4)
        session.flush()
        feedback_id = feedback.id
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        feedback = session.get(RecipeFeedback, feedback_id)
        feedback_service.delete_feedback(session, feedback)

    with session_scope(session_factory) as session:
        assert session.get(RecipeFeedback, feedback_id) is None
        recipe = session.get(Recipe, recipe_id)
        assert recipe.feedback_entries == []
