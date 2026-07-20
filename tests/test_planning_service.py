from datetime import date

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import CampYear
from app.services import planning_service


def test_create_camp_year_rejects_duplicate_year(session_factory) -> None:
    with session_scope(session_factory) as session:
        planning_service.create_camp_year(session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 3))

    with session_scope(session_factory) as session:
        with pytest.raises(ValueError):
            planning_service.create_camp_year(session, year=2026)


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


def test_generate_daily_meal_slots_is_idempotent(session_factory) -> None:
    with session_scope(session_factory) as session:
        camp_year = planning_service.create_camp_year(
            session, year=2026, start_date=date(2026, 8, 1), end_date=date(2026, 8, 1)
        )
        planning_service.generate_daily_meal_slots(session, camp_year)
        second_run = planning_service.generate_daily_meal_slots(session, camp_year)
        assert second_run == []
        assert len(camp_year.meal_plan_entries) == 3


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
