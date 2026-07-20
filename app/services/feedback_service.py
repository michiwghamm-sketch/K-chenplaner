from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import CampYear, Recipe, RecipeFeedback


def calculate_quantity_factor(planned_portions: int | None, cooked_portions: int | None) -> Decimal | None:
    """Mengenfaktor fuers naechste Mal: gekochte Portionen / geplante Portionen."""
    if not planned_portions or not cooked_portions:
        return None
    return (Decimal(cooked_portions) / Decimal(planned_portions)).quantize(Decimal("0.001"))


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
