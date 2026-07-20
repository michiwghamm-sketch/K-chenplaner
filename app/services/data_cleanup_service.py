from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, Recipe, ShoppingListItem
from app.utils.normalization import normalize_name

NON_INGREDIENT_EXACT_NAMES = {
    "Gerichte:",
    "Schnell-Check Preisliste",
    "Artikel gesamt",
    "Preise fehlen",
    "Anteil gepflegt",
}


@dataclass(slots=True)
class CleanupReport:
    deleted_ingredient_names: list[str]
    deleted_shopping_summary_count: int


def is_non_ingredient_name(name: str, *, recipe_names: set[str] | None = None) -> bool:
    stripped = name.strip()
    if not stripped:
        return True
    if stripped in NON_INGREDIENT_EXACT_NAMES:
        return True
    if stripped.startswith("Zutaten:"):
        return True
    normalized = normalize_name(stripped)
    return recipe_names is not None and normalized in recipe_names


def cleanup_non_ingredient_entries(session: Session) -> CleanupReport:
    recipe_names = {
        recipe.normalized_name
        for recipe in session.execute(select(Recipe)).scalars()
    }

    deleted_shopping_summary_count = 0
    shopping_summary_items = session.execute(select(ShoppingListItem)).scalars().all()
    for item in shopping_summary_items:
        ingredient_name = item.ingredient.name if item.ingredient is not None else ""
        if item.unit != "Portionen" and not is_non_ingredient_name(ingredient_name, recipe_names=recipe_names):
            continue
        session.delete(item)
        deleted_shopping_summary_count += 1
    session.flush()
    session.expire_all()

    deleted_ingredient_names: list[str] = []
    ingredients = session.execute(select(Ingredient).order_by(Ingredient.name)).scalars().all()
    for ingredient in ingredients:
        if not is_non_ingredient_name(ingredient.name, recipe_names=recipe_names):
            continue
        if ingredient.recipe_links or ingredient.shopping_items:
            continue
        deleted_ingredient_names.append(ingredient.name)
        session.delete(ingredient)

    return CleanupReport(
        deleted_ingredient_names=deleted_ingredient_names,
        deleted_shopping_summary_count=deleted_shopping_summary_count,
    )
