from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CampYear, Recipe
from app.services import planning_service, recipe_service

UNKNOWN_DIET_TYPE_LABEL = "Ohne Angabe"


def recipe_counts_by_diet_type(session: Session, *, active_only: bool = True) -> dict[str, int]:
    """Anzahl Rezepte je Ernährungstyp (Vegetarisch/Vegan/Fleisch/Ohne Angabe)."""
    stmt = select(Recipe)
    if active_only:
        stmt = stmt.where(Recipe.active.is_(True))
    recipes = session.execute(stmt).scalars().all()
    counter = Counter(recipe.diet_type or UNKNOWN_DIET_TYPE_LABEL for recipe in recipes)
    return dict(counter)


@dataclass(slots=True)
class RecipePlanCount:
    recipe_id: int
    recipe_name: str
    diet_type: str | None
    plan_count: int


def most_planned_recipes(session: Session, *, limit: int = 8, active_only: bool = True) -> list[RecipePlanCount]:
    """Rangliste der am haeufigsten eingeplanten Rezepte ueber alle Camp-Jahre hinweg.

    Zaehlt je Rezept die Anzahl unterschiedlicher Camp-Jahre, in denen es mindestens einmal
    (nicht abgesagt, nicht 'keine Mahlzeit') eingeplant ist - ein Rezept, das in einer Woche
    fuenfmal auf dem Plan steht, zaehlt fuer dieses Jahr trotzdem nur einmal.
    """
    stmt = select(Recipe)
    if active_only:
        stmt = stmt.where(Recipe.active.is_(True))
    recipes = session.execute(stmt).scalars().all()

    counts: list[RecipePlanCount] = []
    for recipe in recipes:
        camp_years_planned = {
            entry.camp_year_id for entry in recipe.meal_plan_entries if planning_service.is_active_status(entry.status)
        }
        plan_count = len(camp_years_planned)
        if plan_count:
            counts.append(
                RecipePlanCount(
                    recipe_id=recipe.id, recipe_name=recipe.name, diet_type=recipe.diet_type, plan_count=plan_count
                )
            )
    counts.sort(key=lambda c: (-c.plan_count, c.recipe_name))
    return counts[:limit]


@dataclass(slots=True)
class CampYearCost:
    camp_year_id: int
    label: str
    year: int
    total_portions: int
    total_cost: Decimal


def camp_year_costs(session: Session) -> list[CampYearCost]:
    """Kalkulierte Gesamtkosten je Camp-Jahr (Rezeptkosten je geplanter Mahlzeit, nicht abgesagte Slots)."""
    camp_years = session.execute(select(CampYear).order_by(CampYear.year.desc())).scalars().all()
    results: list[CampYearCost] = []
    for camp_year in camp_years:
        active_entries = [entry for entry in camp_year.meal_plan_entries if planning_service.is_active_status(entry.status)]
        total_portions = sum(entry.planned_portions or 0 for entry in active_entries)
        total_cost = Decimal("0")
        for entry in active_entries:
            if entry.recipe is None or not entry.planned_portions:
                continue
            cost_result = recipe_service.calculate_recipe_cost(
                session, entry.recipe, portions=entry.planned_portions, year=camp_year.year
            )
            total_cost += cost_result.total_cost
        results.append(
            CampYearCost(
                camp_year_id=camp_year.id,
                label=camp_year.name or str(camp_year.year),
                year=camp_year.year,
                total_portions=total_portions,
                total_cost=total_cost,
            )
        )
    return results


@dataclass(slots=True)
class RecipeCostRank:
    recipe_id: int
    recipe_name: str
    diet_type: str | None
    cost_per_portion: Decimal


def recipe_cost_ranking_for_camp_year(session: Session, camp_year: CampYear) -> list[RecipeCostRank]:
    """Rangliste der in diesem Camp-Jahr eingeplanten Rezepte nach Kosten pro Portion, teuerstes
    zuerst - zeigt auf einen Blick, welches Gericht das Budget am staerksten belastet.

    Rezepte mit fehlenden Zutatenpreisen werden ausgelassen statt mit einem irrefuehrend
    niedrigen (unvollstaendigen) Preis gelistet zu werden.
    """
    recipe_ids = {
        entry.recipe_id
        for entry in camp_year.meal_plan_entries
        if entry.recipe_id is not None and planning_service.is_active_status(entry.status)
    }

    ranking: list[RecipeCostRank] = []
    for recipe_id in recipe_ids:
        recipe = session.get(Recipe, recipe_id)
        if recipe is None:
            continue
        result = recipe_service.calculate_recipe_cost(session, recipe, year=camp_year.year)
        if result.cost_per_portion is None or result.missing_price_ingredients:
            continue
        ranking.append(
            RecipeCostRank(
                recipe_id=recipe.id,
                recipe_name=recipe.name,
                diet_type=recipe.diet_type,
                cost_per_portion=result.cost_per_portion,
            )
        )
    ranking.sort(key=lambda r: (-r.cost_per_portion, r.recipe_name))
    return ranking


@dataclass(slots=True)
class AverageRecipeCost:
    recipes_considered: int
    recipes_total: int
    average_total_cost: Decimal | None
    average_cost_per_portion: Decimal | None


def average_recipe_cost(session: Session, *, active_only: bool = True) -> AverageRecipeCost:
    """Durchschnittliche Rezeptkosten bei Standardportionen, ueber alle Rezepte mit mind.
    einer bepreisten Zutat (nutzt je Zutat den neuesten bekannten Preis, jahresunabhaengig)."""
    stmt = select(Recipe)
    if active_only:
        stmt = stmt.where(Recipe.active.is_(True))
    recipes = session.execute(stmt).scalars().all()

    total_costs: list[Decimal] = []
    per_portion_costs: list[Decimal] = []
    for recipe in recipes:
        if not recipe.ingredients:
            continue
        cost_result = recipe_service.calculate_recipe_cost(session, recipe, portions=recipe.default_portions or 1)
        if cost_result.total_cost > 0:
            total_costs.append(cost_result.total_cost)
        if cost_result.cost_per_portion is not None and cost_result.cost_per_portion > 0:
            per_portion_costs.append(cost_result.cost_per_portion)

    average_total = (sum(total_costs) / len(total_costs)).quantize(Decimal("0.01")) if total_costs else None
    average_per_portion = (
        (sum(per_portion_costs) / len(per_portion_costs)).quantize(Decimal("0.01")) if per_portion_costs else None
    )
    return AverageRecipeCost(
        recipes_considered=len(total_costs),
        recipes_total=len(recipes),
        average_total_cost=average_total,
        average_cost_per_portion=average_per_portion,
    )
