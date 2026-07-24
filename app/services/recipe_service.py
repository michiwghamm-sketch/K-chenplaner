from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Recipe, RecipeComponent, RecipeFeedback, RecipeIngredient, RecipeStep, RecipeVersion
from app.services import price_service
from app.utils.normalization import normalize_name

UNASSIGNED_COMPONENT_LABEL = "Sonstiges"
DIET_TYPES = ("Vegetarisch", "Vegan", "Fleisch")


@dataclass(slots=True)
class ScaledIngredientLine:
    ingredient_name: str
    quantity: Decimal
    unit: str
    optional: bool
    notes: str | None


@dataclass(slots=True)
class IngredientCostLine:
    component_name: str
    ingredient_name: str
    quantity: Decimal
    unit: str
    price_per_unit: Decimal | None
    line_cost: Decimal | None


@dataclass(slots=True)
class RecipeCostResult:
    total_cost: Decimal
    cost_per_portion: Decimal | None
    portions: int
    missing_price_ingredients: list[str] = field(default_factory=list)
    lines: list[IngredientCostLine] = field(default_factory=list)


def scale_recipe(recipe: Recipe, target_portions: int) -> list[ScaledIngredientLine]:
    """Skaliert alle Zutatenmengen eines Rezepts auf die gewuenschte Portionenzahl."""
    if target_portions <= 0:
        raise ValueError("Zielportionen müssen größer als 0 sein.")
    base_portions = recipe.default_portions or target_portions
    if base_portions <= 0:
        raise ValueError("Rezept hat keine gültige Standardportionenzahl.")

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
    """Berechnet Gesamtkosten, Kosten pro Portion und die Kosten je Zutat anhand der besten bekannten Preise."""
    target_portions = portions or recipe.default_portions or 1
    base_portions = recipe.default_portions or target_portions
    factor = Decimal(target_portions) / Decimal(base_portions) if base_portions else Decimal(1)

    total_cost = Decimal("0")
    missing: list[str] = []
    lines: list[IngredientCostLine] = []

    for item in sorted(recipe.ingredients, key=lambda i: i.sort_order):
        best_price = price_service.find_best_price(session, item.ingredient_id, year=year)
        scaled_quantity = (item.quantity * factor).quantize(Decimal("0.001"))
        component_name = item.component.name if item.component else UNASSIGNED_COMPONENT_LABEL
        target_price_unit = item.price_unit or item.unit

        if best_price is None:
            missing.append(item.ingredient.name)
            lines.append(
                IngredientCostLine(
                    component_name=component_name,
                    ingredient_name=item.ingredient.name,
                    quantity=scaled_quantity,
                    unit=item.unit,
                    price_per_unit=None,
                    line_cost=None,
                )
            )
            continue

        if not price_service.can_convert_units(best_price.unit, target_price_unit):
            missing.append(item.ingredient.name)
            lines.append(
                IngredientCostLine(
                    component_name=component_name,
                    ingredient_name=item.ingredient.name,
                    quantity=scaled_quantity,
                    unit=item.unit,
                    price_per_unit=None,
                    line_cost=None,
                )
            )
            continue

        converted_price = price_service.convert_price_per_unit(
            best_price.price_per_unit,
            from_unit=best_price.unit,
            to_unit=target_price_unit,
        ).quantize(Decimal("0.0001"))
        line_cost = (scaled_quantity * converted_price).quantize(Decimal("0.01"))
        total_cost += line_cost
        lines.append(
            IngredientCostLine(
                component_name=component_name,
                ingredient_name=item.ingredient.name,
                quantity=scaled_quantity,
                unit=item.unit,
                price_per_unit=converted_price,
                line_cost=line_cost,
            )
        )

    cost_per_portion = (total_cost / Decimal(target_portions)) if target_portions else None
    return RecipeCostResult(
        total_cost=total_cost.quantize(Decimal("0.01")),
        cost_per_portion=cost_per_portion.quantize(Decimal("0.01")) if cost_per_portion is not None else None,
        portions=target_portions,
        missing_price_ingredients=missing,
        lines=lines,
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


def generate_unique_recipe_name(session: Session, base_name: str = "Neues Rezept") -> str:
    """Findet einen freien Namen für ein neues Rezept (z. B. wenn 'Neues Rezept' bereits existiert)."""
    candidate = base_name
    counter = 2
    while session.execute(select(Recipe).where(Recipe.normalized_name == normalize_name(candidate))).scalar_one_or_none() is not None:
        candidate = f"{base_name} {counter}"
        counter += 1
    return candidate


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


def delete_recipe(session: Session, recipe: Recipe) -> None:
    """Löscht ein Rezept dauerhaft. Schlägt fehl, wenn es noch im Wochenplan verplant ist oder
    Feedback-Einträge hat (dort würden sonst verwaiste Verknüpfungen entstehen) - in dem Fall
    stattdessen deaktivieren oder zuerst aus dem Wochenplan entfernen."""
    if recipe.meal_plan_entries:
        raise ValueError(
            f"'{recipe.name}' ist noch im Wochenplan verplant und kann nicht gelöscht werden. "
            "Bitte zuerst aus dem Wochenplan entfernen oder stattdessen deaktivieren."
        )
    if recipe.feedback_entries:
        raise ValueError(
            f"'{recipe.name}' hat bereits Feedback-Einträge und kann nicht gelöscht werden. "
            "Bitte stattdessen deaktivieren."
        )
    session.delete(recipe)
    session.flush()


def duplicate_recipe(session: Session, recipe: Recipe, *, name: str, diet_type: str | None = None) -> Recipe:
    """Dupliziert ein Rezept (Teilstücke, Zutaten, Kochanleitung) unter neuem Namen.

    Gedacht z. B. für "aus einem Fleischgericht eine vegetarische/vegane Variante machen":
    ein Duplikat mit gesetztem diet_type anlegen und danach in Ruhe die Zutaten anpassen,
    ohne das Originalrezept zu verändern. Historie und Feedback werden bewusst NICHT
    übernommen, da sie sich auf das Originalrezept beziehen.
    """
    new_recipe = Recipe(
        name=name.strip(),
        normalized_name=normalize_name(name),
        category=recipe.category,
        meal_type=recipe.meal_type,
        default_portions=recipe.default_portions,
        instructions=recipe.instructions,
        notes=recipe.notes,
        diet_type=diet_type,
    )
    session.add(new_recipe)
    session.flush()

    component_map: dict[int, RecipeComponent] = {}
    for component in sorted(recipe.components, key=lambda c: c.sort_order):
        new_component = RecipeComponent(
            recipe=new_recipe, name=component.name, sort_order=component.sort_order, notes=component.notes
        )
        session.add(new_component)
        session.flush()
        component_map[component.id] = new_component

    for item in sorted(recipe.ingredients, key=lambda i: i.sort_order):
        session.add(
            RecipeIngredient(
                recipe=new_recipe,
                component=component_map.get(item.component_id) if item.component_id is not None else None,
                ingredient_id=item.ingredient_id,
                quantity=item.quantity,
                unit=item.unit,
                price_unit=item.price_unit,
                optional=item.optional,
                sort_order=item.sort_order,
                notes=item.notes,
            )
        )

    for step in sorted(recipe.steps, key=lambda s: s.sort_order):
        session.add(
            RecipeStep(
                recipe=new_recipe,
                sort_order=step.sort_order,
                title=step.title,
                description=step.description,
                duration_minutes=step.duration_minutes,
            )
        )

    session.flush()
    return new_recipe


# --- Teilstuecke (RecipeComponent) -------------------------------------------------


def create_component(session: Session, recipe: Recipe, name: str, *, notes: str | None = None) -> RecipeComponent:
    sort_order = max((c.sort_order for c in recipe.components), default=0) + 1
    component = RecipeComponent(recipe=recipe, name=name.strip(), sort_order=sort_order, notes=notes)
    session.add(component)
    session.flush()
    return component


def update_component(component: RecipeComponent, **fields: object) -> RecipeComponent:
    for key, value in fields.items():
        if not hasattr(component, key):
            raise AttributeError(f"Unbekanntes Teilstück-Feld: {key}")
        setattr(component, key, value)
    return component


def delete_component(session: Session, component: RecipeComponent) -> None:
    """Loescht ein Teilstueck; seine Zutaten bleiben erhalten und wandern nach 'Sonstiges'."""
    for ingredient in list(component.ingredients):
        ingredient.component_id = None
    session.delete(component)


# --- Zutaten -------------------------------------------------------------------------


def add_ingredient_to_recipe(
    session: Session,
    recipe: Recipe,
    *,
    ingredient_id: int,
    quantity: Decimal,
    unit: str,
    component_id: int | None = None,
    price_unit: str | None = None,
    optional: bool = False,
    notes: str | None = None,
) -> RecipeIngredient:
    sort_order = max((item.sort_order for item in recipe.ingredients), default=0) + 1
    link = RecipeIngredient(
        recipe=recipe,
        ingredient_id=ingredient_id,
        component_id=component_id,
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


# --- Kochanleitung (RecipeStep) --------------------------------------------------------


def create_step(
    session: Session,
    recipe: Recipe,
    *,
    title: str | None = None,
    description: str | None = None,
    duration_minutes: int | None = None,
) -> RecipeStep:
    sort_order = max((s.sort_order for s in recipe.steps), default=0) + 1
    step = RecipeStep(
        recipe=recipe,
        sort_order=sort_order,
        title=title,
        description=description,
        duration_minutes=duration_minutes,
    )
    session.add(step)
    session.flush()
    return step


def update_step(step: RecipeStep, **fields: object) -> RecipeStep:
    for key, value in fields.items():
        if not hasattr(step, key):
            raise AttributeError(f"Unbekanntes Schritt-Feld: {key}")
        setattr(step, key, value)
    return step


def delete_step(session: Session, step: RecipeStep) -> None:
    session.delete(step)


def move_step(session: Session, recipe: Recipe, step: RecipeStep, *, direction: int) -> None:
    """Vertauscht die Reihenfolge mit dem direkten Nachbarn (direction: -1 = nach oben, +1 = nach unten)."""
    ordered_steps = sorted(recipe.steps, key=lambda s: s.sort_order)
    index = ordered_steps.index(step)
    neighbor_index = index + direction
    if not (0 <= neighbor_index < len(ordered_steps)):
        return
    neighbor = ordered_steps[neighbor_index]
    step.sort_order, neighbor.sort_order = neighbor.sort_order, step.sort_order
    session.flush()


def total_step_duration_minutes(recipe: Recipe) -> int:
    return sum(step.duration_minutes or 0 for step in recipe.steps)


# --- Versionierung / Changelog ---------------------------------------------------------


def _serialize_snapshot(recipe: Recipe) -> str:
    components_by_id = {c.id: c.name for c in recipe.components}
    rows = []
    for item in sorted(recipe.ingredients, key=lambda i: i.sort_order):
        rows.append(
            {
                "component_name": components_by_id.get(item.component_id, UNASSIGNED_COMPONENT_LABEL),
                "ingredient_name": item.ingredient.name,
                "quantity": str(item.quantity),
                "unit": item.unit,
                "optional": item.optional,
                "notes": item.notes,
            }
        )
    return json.dumps(rows, ensure_ascii=False)


def parse_version_snapshot(version: RecipeVersion) -> list[dict]:
    return json.loads(version.ingredients_snapshot)


def create_version_snapshot(
    session: Session, recipe: Recipe, *, change_note: str | None = None, scale_factor: Decimal | None = None
) -> RecipeVersion:
    """Friert den aktuellen Zutatenstand als neue Historien-Version ein."""
    next_number = max((v.version_number for v in recipe.versions), default=0) + 1
    version = RecipeVersion(
        recipe=recipe,
        version_number=next_number,
        change_note=change_note,
        scale_factor=scale_factor,
        default_portions=recipe.default_portions,
        ingredients_snapshot=_serialize_snapshot(recipe),
    )
    session.add(version)
    session.flush()
    return version


def list_versions(recipe: Recipe) -> list[RecipeVersion]:
    return sorted(recipe.versions, key=lambda v: v.version_number, reverse=True)


def scale_recipe_ingredients(
    session: Session, recipe: Recipe, factor: Decimal, *, change_note: str | None = None
) -> RecipeVersion:
    """Skaliert alle Zutatenmengen mit einem Faktor. Der vorherige Stand wird als Version gesichert."""
    if factor <= 0:
        raise ValueError("Der Faktor muss größer als 0 sein.")

    version = create_version_snapshot(
        session, recipe, change_note=change_note or f"Mengen skaliert mit Faktor {factor}", scale_factor=factor
    )
    for item in recipe.ingredients:
        item.quantity = (item.quantity * factor).quantize(Decimal("0.001"))
    return version


def update_ingredient_quantity(
    session: Session,
    recipe: Recipe,
    link: RecipeIngredient,
    *,
    quantity: Decimal,
    unit: str | None = None,
    change_note: str | None = None,
) -> RecipeVersion:
    """Passt die Menge einer einzelnen Zutat an. Der vorherige Stand wird als Version gesichert."""
    note = change_note or f"{link.ingredient.name}: {link.quantity} {link.unit} -> {quantity} {unit or link.unit}"
    version = create_version_snapshot(session, recipe, change_note=note)
    link.quantity = quantity
    if unit:
        link.unit = unit
    return version


def suggested_scale_factor(recipe: Recipe) -> Decimal | None:
    """Letzter bekannter Mengenfaktor aus dem Feedback (neuestes Camp-Jahr zuerst)."""
    history = feedback_history(recipe)
    for entry in history:
        if entry.quantity_factor_next_time is not None:
            return entry.quantity_factor_next_time
    return None
