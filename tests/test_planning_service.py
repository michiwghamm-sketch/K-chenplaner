from datetime import date

import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import CampYear, MealPlanEntry
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
