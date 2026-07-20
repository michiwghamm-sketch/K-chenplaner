from decimal import Decimal

import pytest

from app.db import session_scope
from app.models import CampYear, Recipe
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
