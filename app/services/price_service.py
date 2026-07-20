from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientPrice


@dataclass(slots=True)
class PriceComparisonRow:
    ingredient: Ingredient
    price_a: Decimal | None
    price_b: Decimal | None
    difference: Decimal | None
    percent_change: Decimal | None


def find_best_price(session: Session, ingredient_id: int, *, year: int | None = None) -> IngredientPrice | None:
    """Bester Preis fuer eine Zutat: exakter Jahrestreffer, sonst der neueste bekannte Preis."""
    prices = session.execute(
        select(IngredientPrice).where(IngredientPrice.ingredient_id == ingredient_id)
    ).scalars().all()
    if not prices:
        return None

    if year is not None:
        exact_matches = [price for price in prices if price.year == year]
        if exact_matches:
            return max(exact_matches, key=_price_sort_key)

    return find_latest_price_from(prices)


def find_latest_price(session: Session, ingredient_id: int) -> IngredientPrice | None:
    prices = session.execute(
        select(IngredientPrice).where(IngredientPrice.ingredient_id == ingredient_id)
    ).scalars().all()
    return find_latest_price_from(prices)


def find_latest_price_from(prices: list[IngredientPrice]) -> IngredientPrice | None:
    if not prices:
        return None
    return max(prices, key=_price_sort_key)


def _price_sort_key(price: IngredientPrice) -> tuple:
    return (
        price.valid_from or (price.updated_at.date() if price.updated_at else None),
        price.year or 0,
        price.id or 0,
    )


def missing_price_ingredients(session: Session, *, year: int | None = None, active_only: bool = True) -> list[Ingredient]:
    """Zutaten ohne (gueltigen) Preis fuer das angegebene Jahr, bzw. ganz ohne Preis."""
    stmt = select(Ingredient)
    if active_only:
        stmt = stmt.where(Ingredient.active.is_(True))
    ingredients = session.execute(stmt).scalars().all()

    missing = []
    for ingredient in ingredients:
        if year is not None:
            has_price = any(price.year == year for price in ingredient.prices)
        else:
            has_price = len(ingredient.prices) > 0
        if not has_price:
            missing.append(ingredient)
    return missing


def copy_prices_from_year(
    session: Session,
    *,
    source_year: int,
    target_year: int,
    overwrite: bool = False,
) -> int:
    """Kopiert Preise von einem Jahr in ein anderes fuer Zutaten, denen im Zieljahr ein Preis fehlt."""
    source_prices = session.execute(
        select(IngredientPrice).where(IngredientPrice.year == source_year)
    ).scalars().all()

    copied = 0
    for source_price in source_prices:
        existing_target = session.execute(
            select(IngredientPrice).where(
                IngredientPrice.ingredient_id == source_price.ingredient_id,
                IngredientPrice.year == target_year,
            )
        ).scalars().all()
        if existing_target and not overwrite:
            continue
        if existing_target and overwrite:
            for old_price in existing_target:
                session.delete(old_price)

        session.add(
            IngredientPrice(
                ingredient_id=source_price.ingredient_id,
                price_per_unit=source_price.price_per_unit,
                unit=source_price.unit,
                source=source_price.source,
                store=source_price.store,
                year=target_year,
                confidence="uebernommen",
                notes=f"Kopiert aus {source_year}",
            )
        )
        copied += 1
    return copied


def compare_years(session: Session, *, year_a: int, year_b: int) -> list[PriceComparisonRow]:
    ingredients = session.execute(select(Ingredient).order_by(Ingredient.name)).scalars().all()
    rows: list[PriceComparisonRow] = []
    for ingredient in ingredients:
        price_a = next((p.price_per_unit for p in ingredient.prices if p.year == year_a), None)
        price_b = next((p.price_per_unit for p in ingredient.prices if p.year == year_b), None)
        if price_a is None and price_b is None:
            continue
        difference = (price_b - price_a) if price_a is not None and price_b is not None else None
        percent_change = None
        if difference is not None and price_a:
            percent_change = (difference / price_a) * Decimal("100")
        rows.append(
            PriceComparisonRow(
                ingredient=ingredient,
                price_a=price_a,
                price_b=price_b,
                difference=difference,
                percent_change=percent_change,
            )
        )
    return rows
