from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Recipe, RecipeIngredient
from app.services import price_service
from app.utils.normalization import normalize_name


@dataclass(slots=True)
class ScaledIngredientLine:
    ingredient_name: str
    quantity: Decimal
    unit: str
    optional: bool
    notes: str | None


@dataclass(slots=True)
class RecipeCostResult:
    total_cost: Decimal
    cost_per_portion: Decimal | None
    portions: int
    missing_price_ingredients: list[str] = field(default_factory=list)


def scale_recipe(recipe: Recipe, target_portions: int) -> list[ScaledIngredientLine]:
    """Skaliert alle Zutatenmengen eines Rezepts auf die gewuenschte Portionenzahl."""
    if target_portions <= 0:
        raise ValueError("Zielportionen muessen groesser als 0 sein.")
    base_portions = recipe.default_portions or target_portions
    if base_portions <= 0:
        raise ValueError("Rezept hat keine gueltige Standardportionenzahl.")

    factor = Decimal(target_portions) / Decimal(base_portions)
    lines: list[ScaledIngredientLine] = []
    for item in sorted(recipe.ingredients, key=lambda i: i.sort_order):
        lines.append(
            ScaledIngredientLine(
                ingredient_name=item.ingredient.name,
                quantity=(item.quantity * factor).quantize(Decimal("0.001")),
                unit=item.unit,
                optional=item.optional,
                notes=item.notes,
            )
        )
    return lines


def calculate_recipe_cost(session: Session, recipe: Recipe, *, portions: int | None = None, year: int | None = None) -> RecipeCostResult:
    """Berechnet Gesamtkosten und Kosten pro Portion fuer ein Rezept anhand der besten bekannten Preise."""
    target_portions = portions or recipe.default_portions or 1
    base_portions = recipe.default_portions or target_portions
    factor = Decimal(target_portions) / Decimal(base_portions) if base_portions else Decimal(1)

    total_cost = Decimal("0")
    missing: list[str] = []

    for item in recipe.ingredients:
        best_price = price_service.find_best_price(session, item.ingredient_id, year=year)
        if best_price is None:
            missing.append(item.ingredient.name)
            continue
        scaled_quantity = item.quantity * factor
        total_cost += scaled_quantity * best_price.price_per_unit

    cost_per_portion = (total_cost / Decimal(target_portions)) if target_portions else None
    return RecipeCostResult(
        total_cost=total_cost.quantize(Decimal("0.01")),
        cost_per_portion=cost_per_portion.quantize(Decimal("0.01")) if cost_per_portion is not None else None,
        portions=target_portions,
        missing_price_ingredients=missing,
    )


def search_recipes(
    session: Session,
    *,
    query: str | None = None,
    category: str | None = None,
    meal_type: str | None = None,
    active_only: bool = True,
) -> list[Recipe]:
    stmt = select(Recipe)
    if active_only:
        stmt = stmt.where(Recipe.active.is_(True))
    if category:
        stmt = stmt.where(Recipe.category == category)
    if meal_type:
        stmt = stmt.where(Recipe.meal_type == meal_type)

    recipes = session.execute(stmt.order_by(Recipe.name)).scalars().all()
    if query:
        normalized_query = normalize_name(query)
        recipes = [r for r in recipes if normalized_query in r.normalized_name]
    return recipes


def create_recipe(
    session: Session,
    *,
    name: str,
    category: str | None = None,
    meal_type: str | None = None,
    default_portions: int | None = None,
    instructions: str | None = None,
    notes: str | None = None,
) -> Recipe:
    recipe = Recipe(
        name=name.strip(),
        normalized_name=normalize_name(name),
        category=category,
        meal_type=meal_type,
        default_portions=default_portions,
        instructions=instructions,
        notes=notes,
    )
    session.add(recipe)
    session.flush()
    return recipe


def update_recipe(recipe: Recipe, **fields: object) -> Recipe:
    for key, value in fields.items():
        if not hasattr(recipe, key):
            raise AttributeError(f"Unbekanntes Rezeptfeld: {key}")
        setattr(recipe, key, value)
    if "name" in fields:
        recipe.normalized_name = normalize_name(recipe.name)
    return recipe


def deactivate_recipe(recipe: Recipe) -> None:
    recipe.active = False


def activate_recipe(recipe: Recipe) -> None:
    recipe.active = True


def add_ingredient_to_recipe(
    session: Session,
    recipe: Recipe,
    *,
    ingredient_id: int,
    quantity: Decimal,
    unit: str,
    price_unit: str | None = None,
    optional: bool = False,
    notes: str | None = None,
) -> RecipeIngredient:
    sort_order = max((item.sort_order for item in recipe.ingredients), default=0) + 1
    link = RecipeIngredient(
        recipe=recipe,
        ingredient_id=ingredient_id,
        quantity=quantity,
        unit=unit,
        price_unit=price_unit or unit,
        optional=optional,
        sort_order=sort_order,
        notes=notes,
    )
    session.add(link)
    return link


def remove_ingredient_from_recipe(session: Session, link: RecipeIngredient) -> None:
    session.delete(link)


def feedback_history(recipe: Recipe) -> list:
    return sorted(recipe.feedback_entries, key=lambda entry: entry.camp_year.year if entry.camp_year else 0, reverse=True)
