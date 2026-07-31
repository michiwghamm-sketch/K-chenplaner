from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CampDay, CampYear, MealPlanEntry, Recipe
from app.services import recipe_service

NO_MEAL_STATUS = "keine Mahlzeit"
ALLOWED_STATUSES = ("geplant", "bestellt", "gekocht", "abgesagt", NO_MEAL_STATUS)
# Status-Werte, die einen Slot von allen Zaehlungen/Kosten/Warnungen ausschliessen: 'abgesagt'
# (eine geplante Mahlzeit ist ausgefallen) und 'keine Mahlzeit' (an diesem Slot ist von vornherein
# keine Mahlzeit vorgesehen, z. B. kein Abendessen am Anreisetag) - beides sind bewusst keine
# "offenen" Slots, die noch ein Rezept brauchen.
INACTIVE_STATUSES = ("abgesagt", NO_MEAL_STATUS)
DEFAULT_MEAL_TYPES = ("Frühstück", "Mittagessen", "Abendessen")


def is_active_status(status: str | None) -> bool:
    return status not in INACTIVE_STATUSES

WEEKDAY_NAMES_DE = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)


def weekday_name(day: date) -> str:
    return WEEKDAY_NAMES_DE[day.weekday()]


def create_camp_year(
    session: Session,
    *,
    year: int,
    name: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    participant_count_children: int | None = None,
    participant_count_adults: int | None = None,
    location: str | None = None,
    notes: str | None = None,
) -> CampYear:
    existing = session.execute(select(CampYear).where(CampYear.year == year)).scalar_one_or_none()
    if existing is not None:
        raise ValueError(f"Camp-Jahr {year} existiert bereits.")

    total = None
    if participant_count_children is not None or participant_count_adults is not None:
        total = (participant_count_children or 0) + (participant_count_adults or 0)

    camp_year = CampYear(
        year=year,
        name=name or f"Zeltlager {year}",
        start_date=start_date,
        end_date=end_date,
        participant_count_children=participant_count_children,
        participant_count_adults=participant_count_adults,
        participant_count_total=total,
        location=location,
        notes=notes,
    )
    session.add(camp_year)
    session.flush()
    return camp_year


def update_camp_year(session: Session, camp_year: CampYear, *, year: int | None = None, **fields: object) -> CampYear:
    if year is not None and year != camp_year.year:
        existing = session.execute(select(CampYear).where(CampYear.year == year)).scalar_one_or_none()
        if existing is not None:
            raise ValueError(f"Camp-Jahr {year} existiert bereits.")
        camp_year.year = year

    for key, value in fields.items():
        if not hasattr(camp_year, key):
            raise AttributeError(f"Unbekanntes Camp-Jahr-Feld: {key}")
        setattr(camp_year, key, value)

    # Gesamtzahl bei jeder Aenderung der Einzelwerte neu ableiten, wie beim Anlegen - sonst
    # veraltet participant_count_total stillschweigend, sobald Kinder/Erwachsene bearbeitet werden.
    if "participant_count_children" in fields or "participant_count_adults" in fields:
        camp_year.participant_count_total = (camp_year.participant_count_children or 0) + (
            camp_year.participant_count_adults or 0
        )
    return camp_year


def days_until_start(camp_year: CampYear, *, today: date | None = None) -> int | None:
    """Tage bis Zeltlagerbeginn (negativ, wenn es schon begonnen hat). None ohne Startdatum."""
    if camp_year.start_date is None:
        return None
    reference = today or date.today()
    return (camp_year.start_date - reference).days


def meal_plan_completeness(camp_year: CampYear) -> tuple[int, int]:
    """(Anzahl Slots mit zugewiesenem Rezept, Anzahl aktiver Slots insgesamt) - fuer eine
    'X von Y Mahlzeiten geplant'-Anzeige. Abgesagte und 'keine Mahlzeit'-Slots zaehlen nicht mit."""
    active_entries = [entry for entry in camp_year.meal_plan_entries if is_active_status(entry.status)]
    filled = sum(1 for entry in active_entries if entry.recipe is not None)
    return filled, len(active_entries)


def generate_daily_meal_slots(
    session: Session,
    camp_year: CampYear,
    *,
    meal_types: tuple[str, ...] = DEFAULT_MEAL_TYPES,
) -> list[MealPlanEntry]:
    """Legt fuer jeden Tag im Camp-Zeitraum leere Mahlzeiten-Slots an, sofern noch keine existieren."""
    if camp_year.start_date is None or camp_year.end_date is None:
        raise ValueError("Camp-Jahr benötigt Start- und Enddatum für die automatische Planung.")

    existing_keys = {(entry.meal_date, entry.meal_type) for entry in camp_year.meal_plan_entries}
    existing_days = {day.day_date for day in camp_year.camp_days}

    created: list[MealPlanEntry] = []
    current_day = camp_year.start_date
    while current_day <= camp_year.end_date:
        if current_day not in existing_days:
            session.add(
                CampDay(camp_year=camp_year, day_date=current_day, weekday=weekday_name(current_day))
            )
            existing_days.add(current_day)

        for meal_type in meal_types:
            if (current_day, meal_type) in existing_keys:
                continue
            entry = MealPlanEntry(
                camp_year=camp_year,
                meal_date=current_day,
                weekday=weekday_name(current_day),
                meal_type=meal_type,
                status="geplant",
            )
            session.add(entry)
            created.append(entry)
        current_day += timedelta(days=1)
    return created


def camp_day_range(camp_year: CampYear) -> list[date]:
    """Liste aller Tage im Camp-Zeitraum (Start- bis Enddatum, inklusive)."""
    if camp_year.start_date is None or camp_year.end_date is None:
        return []
    days = []
    current_day = camp_year.start_date
    while current_day <= camp_year.end_date:
        days.append(current_day)
        current_day += timedelta(days=1)
    return days


def get_or_create_camp_day(session: Session, camp_year: CampYear, day_date: date) -> CampDay:
    session.flush()
    camp_day = session.execute(
        select(CampDay).where(CampDay.camp_year_id == camp_year.id, CampDay.day_date == day_date)
    ).scalar_one_or_none()
    if camp_day is None:
        camp_day = CampDay(camp_year=camp_year, day_date=day_date, weekday=weekday_name(day_date))
        session.add(camp_day)
        session.flush()
    return camp_day


def set_day_responsible(camp_day: CampDay, *, responsible_person: str | None = None, notes: str | None = None) -> CampDay:
    camp_day.responsible_person = responsible_person
    camp_day.notes = notes
    return camp_day


def get_or_create_meal_entry(session: Session, camp_year: CampYear, day_date: date, meal_type: str) -> MealPlanEntry:
    # Sessions use autoflush=False (siehe app/db.py); ohne expliziten Flush wuerden
    # noch nicht geschriebene Eintraege (z. B. aus generate_daily_meal_slots) hier
    # nicht gefunden und faelschlich doppelt angelegt.
    session.flush()
    entry = session.execute(
        select(MealPlanEntry).where(
            MealPlanEntry.camp_year_id == camp_year.id,
            MealPlanEntry.meal_date == day_date,
            MealPlanEntry.meal_type == meal_type,
        )
    ).scalar_one_or_none()
    if entry is None:
        entry = MealPlanEntry(
            camp_year=camp_year,
            meal_date=day_date,
            weekday=weekday_name(day_date),
            meal_type=meal_type,
            status="geplant",
        )
        session.add(entry)
        session.flush()
    return entry


def set_meal_recipe(
    entry: MealPlanEntry,
    *,
    recipe: Recipe | None,
    planned_portions: int | None = None,
    target_group: str | None = None,
) -> MealPlanEntry:
    entry.recipe = recipe
    if planned_portions is not None:
        entry.planned_portions = planned_portions
    if target_group is not None:
        entry.target_group = target_group
    return entry


def set_status(entry: MealPlanEntry, status: str) -> MealPlanEntry:
    if status not in ALLOWED_STATUSES:
        raise ValueError(f"Ungültiger Status '{status}'. Erlaubt: {', '.join(ALLOWED_STATUSES)}")
    entry.status = status
    return entry


def derive_shopping_date(meal_date: date, *, days_before: int = 1) -> date:
    return meal_date - timedelta(days=days_before)


def meal_entries_for_slot(camp_year: CampYear, day_date: date, meal_type: str) -> list[MealPlanEntry]:
    """Alle Gerichte, die fuer einen Tag/Mahlzeitart-Slot eingeplant sind (mehrere pro Slot moeglich)."""
    return sorted(
        (entry for entry in camp_year.meal_plan_entries if entry.meal_date == day_date and entry.meal_type == meal_type),
        key=lambda entry: entry.id or 0,
    )


def add_meal_entry(
    session: Session,
    camp_year: CampYear,
    day_date: date,
    meal_type: str,
    *,
    recipe: Recipe | None = None,
    planned_portions: int | None = None,
    target_group: str | None = None,
) -> MealPlanEntry:
    """Legt ein weiteres Gericht in einem Tag/Mahlzeitart-Slot an, ohne bestehende Gerichte zu ersetzen."""
    entry = MealPlanEntry(
        camp_year=camp_year,
        meal_date=day_date,
        weekday=weekday_name(day_date),
        meal_type=meal_type,
        recipe=recipe,
        planned_portions=planned_portions,
        target_group=target_group,
        status="geplant",
    )
    session.add(entry)
    session.flush()
    return entry


def delete_meal_entry(session: Session, entry: MealPlanEntry) -> None:
    # Feedback haengt seit der (Camp-Jahr, Rezept)-Umstellung nicht mehr an einem einzelnen Slot -
    # das Entfernen eines Mahlzeit-Slots kann also nie mehr ein bestehendes Feedback verwaisen
    # lassen (anders als frueher, als Feedback 1:1 an einem Mahlzeit-Slot haengte).
    session.delete(entry)
    session.flush()


@dataclass(slots=True)
class DayMealCost:
    meal_type: str
    recipe_name: str
    portions: int
    cost: Decimal
    has_missing_prices: bool


@dataclass(slots=True)
class DaySummary:
    day: date
    meals: list[DayMealCost] = field(default_factory=list)
    total_portions: int = 0
    total_cost: Decimal = Decimal("0")
    has_missing_prices: bool = False


def day_summary(session: Session, camp_year: CampYear, day_date: date) -> DaySummary:
    """Kalkulierte Auswertung eines einzelnen Tages: Gerichte, Portionen und Kosten (nicht abgesagte Gerichte)."""
    entries = sorted(
        (
            entry
            for entry in camp_year.meal_plan_entries
            if entry.meal_date == day_date and is_active_status(entry.status) and entry.recipe is not None
        ),
        key=lambda entry: (
            DEFAULT_MEAL_TYPES.index(entry.meal_type) if entry.meal_type in DEFAULT_MEAL_TYPES else len(DEFAULT_MEAL_TYPES),
            entry.id or 0,
        ),
    )

    summary = DaySummary(day=day_date)
    for entry in entries:
        portions = entry.planned_portions or entry.recipe.default_portions or 0
        cost = Decimal("0")
        has_missing_prices = False
        if portions:
            cost_result = recipe_service.calculate_recipe_cost(
                session, entry.recipe, portions=portions, year=camp_year.year
            )
            cost = cost_result.total_cost
            has_missing_prices = bool(cost_result.missing_price_ingredients)

        summary.meals.append(
            DayMealCost(
                meal_type=entry.meal_type or "",
                recipe_name=entry.recipe.name,
                portions=portions,
                cost=cost,
                has_missing_prices=has_missing_prices,
            )
        )
        summary.total_portions += portions
        summary.total_cost += cost
        summary.has_missing_prices = summary.has_missing_prices or has_missing_prices

    return summary
