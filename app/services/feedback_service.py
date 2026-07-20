from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CampYear, MealPlanEntry, Recipe, RecipeFeedback

QUANTITY_SUFFICIENT_OPTIONS = ("Unbekannt", "Ja, hat gereicht", "Zu wenig", "Zu viel")


def calculate_quantity_factor(planned_portions: int | None, cooked_portions: int | None) -> Decimal | None:
    """Mengenfaktor fuers naechste Mal: gekochte Portionen / geplante Portionen."""
    if not planned_portions or not cooked_portions:
        return None
    return (Decimal(cooked_portions) / Decimal(planned_portions)).quantize(Decimal("0.001"))


def list_feedback_candidates(session: Session, camp_year: CampYear) -> list[MealPlanEntry]:
    """Alle Mahlzeiten des Wochenplans, fuer die sinnvoll Feedback erfasst werden kann (Rezept gesetzt, nicht abgesagt)."""
    entries = [
        entry
        for entry in camp_year.meal_plan_entries
        if entry.recipe is not None and entry.status != "abgesagt"
    ]
    return sorted(entries, key=lambda entry: (entry.meal_date or date.min, entry.meal_type or ""))


def get_or_create_meal_feedback(session: Session, meal_plan_entry: MealPlanEntry) -> RecipeFeedback:
    """Holt oder legt das Feedback fuer eine konkrete Mahlzeit im Wochenplan an (ein Feedback je Mahlzeit-Slot)."""
    session.flush()
    feedback = session.execute(
        select(RecipeFeedback).where(RecipeFeedback.meal_plan_entry_id == meal_plan_entry.id)
    ).scalar_one_or_none()
    if feedback is None:
        feedback = RecipeFeedback(
            camp_year_id=meal_plan_entry.camp_year_id,
            recipe_id=meal_plan_entry.recipe_id,
            meal_plan_entry_id=meal_plan_entry.id,
            planned_portions=meal_plan_entry.planned_portions,
        )
        session.add(feedback)
        session.flush()
    return feedback


def save_meal_feedback(
    session: Session,
    meal_plan_entry: MealPlanEntry,
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

    feedback = get_or_create_meal_feedback(session, meal_plan_entry)
    feedback.rating = rating
    feedback.repeat_next_time = repeat_next_time
    feedback.quantity_sufficient = quantity_sufficient
    feedback.planned_portions = planned_portions if planned_portions is not None else meal_plan_entry.planned_portions
    feedback.cooked_portions = cooked_portions
    feedback.leftover_quantity = leftover_quantity
    feedback.leftover_unit = leftover_unit
    feedback.quantity_factor_next_time = calculate_quantity_factor(feedback.planned_portions, cooked_portions)
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
