from __future__ import annotations

import difflib
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CampYear, Ingredient, MealPlanEntry, Recipe, RecipeIngredient, ShoppingList
from app.services import planning_service, price_service, unit_service

DUPLICATE_SIMILARITY_THRESHOLD = 0.88


@dataclass(slots=True)
class ValidationIssue:
    category: str
    severity: str
    message: str
    reference: str | None = None


@dataclass(slots=True)
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, category: str, severity: str, message: str, reference: str | None = None) -> None:
        self.issues.append(ValidationIssue(category, severity, message, reference))

    @property
    def has_critical(self) -> bool:
        return any(issue.severity == "kritisch" for issue in self.issues)


def find_missing_prices(session: Session, *, year: int | None = None) -> list[Ingredient]:
    return price_service.missing_price_ingredients(session, year=year)


def find_missing_units(session: Session) -> list[Ingredient]:
    ingredients = session.execute(select(Ingredient).where(Ingredient.active.is_(True))).scalars().all()
    return [ingredient for ingredient in ingredients if not ingredient.default_unit]


def find_recipe_ingredient_unit_mismatches(session: Session) -> list[tuple[Recipe, Ingredient, RecipeIngredient]]:
    """Findet Rezeptzutaten, deren Einheit nicht (mehr) zur Standardeinheit ihrer Zutat passt.

    Das betrifft nur Altdaten von vor der Einfuehrung des Einheiten-Pools (siehe
    scripts/cleanup_units.py) - neue Eintraege verhindert bereits recipe_service beim Speichern.
    """
    mismatches: list[tuple[Recipe, Ingredient, RecipeIngredient]] = []
    ingredients = session.execute(select(Ingredient)).scalars().all()
    for ingredient in ingredients:
        if not ingredient.default_unit:
            continue
        compatible = set(unit_service.compatible_units(session, ingredient.default_unit, active_only=False))
        for link in ingredient.recipe_links:
            if link.unit not in compatible:
                mismatches.append((link.recipe, ingredient, link))
    return mismatches


def find_recipes_without_ingredients(session: Session) -> list[Recipe]:
    recipes = session.execute(select(Recipe).where(Recipe.active.is_(True))).scalars().all()
    return [recipe for recipe in recipes if not recipe.ingredients]


def find_meal_plan_without_portions(session: Session, camp_year: CampYear) -> list[MealPlanEntry]:
    return [
        entry
        for entry in camp_year.meal_plan_entries
        if entry.recipe is not None and not entry.planned_portions and planning_service.is_scheduled_entry(entry)
    ]


def find_shopping_items_zero_price(shopping_list: ShoppingList) -> list:
    return [
        item
        for item in shopping_list.items
        if item.estimated_price_per_unit is None or item.estimated_price_per_unit == 0
    ]


def find_duplicate_ingredients_without_alias(session: Session) -> list[tuple[Ingredient, Ingredient, float]]:
    """Findet Zutatenpaare mit sehr aehnlichem Namen, die noch nicht per Alias verknuepft sind."""
    ingredients = session.execute(select(Ingredient).where(Ingredient.active.is_(True))).scalars().all()
    duplicates: list[tuple[Ingredient, Ingredient, float]] = []

    for i, first in enumerate(ingredients):
        first_aliases = {alias.alias for alias in first.aliases}
        for second in ingredients[i + 1 :]:
            if second.name in first_aliases or first.name in {a.alias for a in second.aliases}:
                continue
            ratio = difflib.SequenceMatcher(None, first.normalized_name, second.normalized_name).ratio()
            if ratio >= DUPLICATE_SIMILARITY_THRESHOLD:
                duplicates.append((first, second, ratio))
    return duplicates


def run_all_checks(session: Session, *, camp_year: CampYear | None = None, year: int | None = None) -> ValidationReport:
    report = ValidationReport()

    for ingredient in find_missing_prices(session, year=year):
        report.add("preis", "warnung", f"Kein Preis für '{ingredient.name}' hinterlegt.", ingredient.name)

    for ingredient in find_missing_units(session):
        report.add("einheit", "warnung", f"Keine Standardeinheit für '{ingredient.name}' hinterlegt.", ingredient.name)

    for recipe in find_recipes_without_ingredients(session):
        report.add("rezept", "warnung", f"Rezept '{recipe.name}' hat keine Zutaten.", recipe.name)

    for recipe, ingredient, link in find_recipe_ingredient_unit_mismatches(session):
        report.add(
            "einheit",
            "warnung",
            f"'{ingredient.name}' wird in Rezept '{recipe.name}' mit der Einheit '{link.unit}' verwendet - "
            f"das passt nicht zur Standardeinheit '{ingredient.default_unit}'.",
            f"{ingredient.name} / {recipe.name}",
        )

    if camp_year is not None:
        for entry in find_meal_plan_without_portions(session, camp_year):
            report.add(
                "planung",
                "warnung",
                f"Geplante Mahlzeit ohne Portionenzahl am {entry.meal_date}.",
                f"{entry.meal_type} {entry.meal_date}",
            )

    for first, second, ratio in find_duplicate_ingredients_without_alias(session):
        report.add(
            "zutat",
            "hinweis",
            f"'{first.name}' und '{second.name}' sind sich sehr ähnlich ({ratio:.0%}) - eventuell Dubletten.",
            f"{first.name} / {second.name}",
        )

    return report
