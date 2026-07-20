from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientAlias
from app.utils.normalization import normalize_name


def search_ingredients(session: Session, *, query: str | None = None, active_only: bool = True) -> list[Ingredient]:
    stmt = select(Ingredient)
    if active_only:
        stmt = stmt.where(Ingredient.active.is_(True))
    ingredients = session.execute(stmt.order_by(Ingredient.name)).scalars().all()
    if query:
        normalized_query = normalize_name(query)
        ingredients = [
            ingredient
            for ingredient in ingredients
            if normalized_query in ingredient.normalized_name
            or any(normalized_query in normalize_name(alias.alias) for alias in ingredient.aliases)
        ]
    return ingredients


def create_ingredient(
    session: Session,
    *,
    name: str,
    default_unit: str | None = None,
    category: str | None = None,
    storage_type: str | None = None,
    notes: str | None = None,
) -> Ingredient:
    ingredient = Ingredient(
        name=name.strip(),
        normalized_name=normalize_name(name),
        default_unit=default_unit,
        category=category,
        storage_type=storage_type,
        notes=notes,
    )
    session.add(ingredient)
    session.flush()
    return ingredient


def update_ingredient(ingredient: Ingredient, **fields: object) -> Ingredient:
    for key, value in fields.items():
        if not hasattr(ingredient, key):
            raise AttributeError(f"Unbekanntes Zutatenfeld: {key}")
        setattr(ingredient, key, value)
    if "name" in fields:
        ingredient.normalized_name = normalize_name(ingredient.name)
    return ingredient


def deactivate_ingredient(ingredient: Ingredient) -> None:
    ingredient.active = False


def activate_ingredient(ingredient: Ingredient) -> None:
    ingredient.active = True


def add_alias(session: Session, ingredient: Ingredient, alias: str, *, notes: str | None = None) -> IngredientAlias:
    existing = session.execute(
        select(IngredientAlias).where(
            IngredientAlias.ingredient_id == ingredient.id,
            IngredientAlias.alias == alias.strip(),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    alias_record = IngredientAlias(ingredient=ingredient, alias=alias.strip(), notes=notes)
    session.add(alias_record)
    return alias_record


def remove_alias(session: Session, alias_record: IngredientAlias) -> None:
    session.delete(alias_record)


def find_by_name_or_alias(session: Session, name: str) -> Ingredient | None:
    normalized = normalize_name(name)
    ingredient = session.execute(
        select(Ingredient).where(Ingredient.normalized_name == normalized)
    ).scalar_one_or_none()
    if ingredient is not None:
        return ingredient

    alias_record = session.execute(
        select(IngredientAlias).where(IngredientAlias.alias == name.strip())
    ).scalar_one_or_none()
    return alias_record.ingredient if alias_record else None
