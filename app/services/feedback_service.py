from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CampYear, MealPlanEntry, Recipe, RecipeFeedback
from app.services import planning_service

QUANTITY_SUFFICIENT_OPTIONS = ("Unbekannt", "Ja, hat gereicht", "Zu wenig", "Zu viel")


def calculate_quantity_factor(planned_portions: int | None, cooked_portions: int | None) -> Decimal | None:
    """Mengenfaktor fuers naechste Mal: gekochte Portionen / geplante Portionen."""
    if not planned_portions or not cooked_portions:
        return None
    return (Decimal(cooked_portions) / Decimal(planned_portions)).quantize(Decimal("0.001"))


@dataclass(slots=True)
class FeedbackCandidate:
    """Ein Rezept, das in einem Camp-Jahr mindestens einmal aktiv eingeplant ist - Zeile in der
    Feedback-Liste. Ein Rezept, das mehrfach auf dem Plan steht (z. B. Fruehstueck an 5 Tagen),
    bekommt trotzdem nur einen Kandidaten/ein Formular statt einem je Mahlzeit-Slot."""

    recipe_id: int
    recipe_name: str
    occurrences: list[MealPlanEntry] = field(default_factory=list)

    @property
    def occurrence_count(self) -> int:
        return len(self.occurrences)

    @property
    def total_planned_portions(self) -> int:
        return sum(entry.planned_portions or 0 for entry in self.occurrences)

    @property
    def first_date(self) -> date | None:
        dates = [entry.meal_date for entry in self.occurrences if entry.meal_date]
        return min(dates) if dates else None


def list_feedback_candidates(session: Session, camp_year: CampYear) -> list[FeedbackCandidate]:
    """Je Rezept, das in diesem Camp-Jahr mindestens einmal aktiv eingeplant ist, ein Kandidat."""
    entries = [
        entry
        for entry in camp_year.meal_plan_entries
        if entry.recipe is not None and planning_service.is_scheduled_entry(entry)
    ]

    by_recipe: dict[int, FeedbackCandidate] = {}
    for entry in entries:
        candidate = by_recipe.get(entry.recipe_id)
        if candidate is None:
            candidate = FeedbackCandidate(recipe_id=entry.recipe_id, recipe_name=entry.recipe.name)
            by_recipe[entry.recipe_id] = candidate
        candidate.occurrences.append(entry)

    candidates = list(by_recipe.values())
    for candidate in candidates:
        candidate.occurrences.sort(key=lambda entry: (entry.meal_date or date.min, entry.meal_type or ""))
    candidates.sort(key=lambda c: (c.first_date or date.min, c.recipe_name))
    return candidates


def get_feedback(session: Session, camp_year_id: int, recipe_id: int) -> RecipeFeedback | None:
    return session.execute(
        select(RecipeFeedback).where(
            RecipeFeedback.camp_year_id == camp_year_id, RecipeFeedback.recipe_id == recipe_id
        )
    ).scalar_one_or_none()


def get_or_create_feedback(session: Session, camp_year: CampYear, recipe: Recipe) -> RecipeFeedback:
    """Holt oder legt das Feedback fuer ein Rezept in einem Camp-Jahr an (ein Feedback je
    Rezept/Jahr, unabhaengig davon, wie oft es diese Woche auf dem Plan steht)."""
    session.flush()
    feedback = get_feedback(session, camp_year.id, recipe.id)
    if feedback is None:
        feedback = RecipeFeedback(camp_year_id=camp_year.id, recipe_id=recipe.id)
        session.add(feedback)
        session.flush()
    return feedback


def save_feedback(
    session: Session,
    camp_year: CampYear,
    recipe: Recipe,
    *,
    rating: int | None = None,
    repeat_next_time: bool | None = None,
    quantity_sufficient: str | None = None,
    planned_portions: int | None = None,
    cooked_portions: int | None = None,
    leftover_quantity: Decimal | None = None,
    leftover_unit: str | None = None,
    process_tips: str | None = None,
    what_went_well: str | None = None,
    what_to_change: str | None = None,
) -> RecipeFeedback:
    if rating is not None and not (1 <= rating <= 5):
        raise ValueError("Bewertung muss zwischen 1 und 5 liegen.")

    feedback = get_or_create_feedback(session, camp_year, recipe)
    feedback.rating = rating
    feedback.repeat_next_time = repeat_next_time
    feedback.quantity_sufficient = quantity_sufficient
    feedback.planned_portions = planned_portions
    feedback.cooked_portions = cooked_portions
    feedback.quantity_factor_next_time = calculate_quantity_factor(planned_portions, cooked_portions)
    feedback.leftover_quantity = leftover_quantity
    feedback.leftover_unit = leftover_unit
    feedback.process_tips = process_tips
    feedback.what_went_well = what_went_well
    feedback.what_to_change = what_to_change
    return feedback


def record_feedback(
    session: Session,
    *,
    camp_year: CampYear,
    recipe: Recipe,
    rating: int | None = None,
    repeat_next_time: bool | None = None,
    planned_portions: int | None = None,
    cooked_portions: int | None = None,
    leftover_quantity: Decimal | None = None,
    leftover_unit: str | None = None,
    process_tips: str | None = None,
    what_went_well: str | None = None,
    what_to_change: str | None = None,
) -> RecipeFeedback:
    """Legt ein freistehendes Feedback ohne Mahlzeit-Bezug an (z. B. fuer Alt-/Importdaten)."""
    if rating is not None and not (1 <= rating <= 5):
        raise ValueError("Bewertung muss zwischen 1 und 5 liegen.")

    feedback = RecipeFeedback(
        camp_year=camp_year,
        recipe=recipe,
        rating=rating,
        repeat_next_time=repeat_next_time,
        planned_portions=planned_portions,
        cooked_portions=cooked_portions,
        leftover_quantity=leftover_quantity,
        leftover_unit=leftover_unit,
        quantity_factor_next_time=calculate_quantity_factor(planned_portions, cooked_portions),
        process_tips=process_tips,
        what_went_well=what_went_well,
        what_to_change=what_to_change,
    )
    session.add(feedback)
    session.flush()
    return feedback


def update_feedback(feedback: RecipeFeedback, **fields: object) -> RecipeFeedback:
    for key, value in fields.items():
        if not hasattr(feedback, key):
            raise AttributeError(f"Unbekanntes Feedbackfeld: {key}")
        setattr(feedback, key, value)
    if "planned_portions" in fields or "cooked_portions" in fields:
        feedback.quantity_factor_next_time = calculate_quantity_factor(
            feedback.planned_portions, feedback.cooked_portions
        )
    return feedback


def recipe_feedback_history(recipe: Recipe) -> list[RecipeFeedback]:
    return sorted(
        recipe.feedback_entries,
        key=lambda entry: entry.camp_year.year if entry.camp_year else 0,
        reverse=True,
    )


def delete_feedback(session: Session, feedback: RecipeFeedback) -> None:
    session.delete(feedback)
    session.flush()
