from decimal import Decimal

from sqlalchemy import select

from app.db import session_scope
from app.models import Ingredient, IngredientPrice
from app.services import price_service


def test_multiple_prices_can_be_stored_for_one_ingredient(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Tomaten", normalized_name="tomaten", default_unit="kg")
        ingredient.prices.extend(
            [
                IngredientPrice(price_per_unit=Decimal("1.99"), unit="kg", year=2025, source="Preisliste 2025"),
                IngredientPrice(price_per_unit=Decimal("2.49"), unit="kg", year=2026, source="Preisliste 2026"),
            ]
        )
        session.add(ingredient)

    with session_scope(session_factory) as session:
        stored = session.execute(select(Ingredient).where(Ingredient.normalized_name == "tomaten")).scalar_one()
        prices_by_year = {price.year: price.price_per_unit for price in stored.prices}
        assert prices_by_year[2025] == Decimal("1.99")
        assert prices_by_year[2026] == Decimal("2.49")


def test_find_best_price_prefers_exact_year_match(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Reis", normalized_name="reis", default_unit="kg")
        ingredient.prices.extend(
            [
                IngredientPrice(price_per_unit=Decimal("1.50"), unit="kg", year=2024),
                IngredientPrice(price_per_unit=Decimal("1.80"), unit="kg", year=2026),
            ]
        )
        session.add(ingredient)
        session.flush()
        ingredient_id = ingredient.id

    with session_scope(session_factory) as session:
        best = price_service.find_best_price(session, ingredient_id, year=2026)
        assert best.price_per_unit == Decimal("1.80")


def test_find_best_price_falls_back_to_latest_when_year_missing(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Mehl", normalized_name="mehl", default_unit="kg")
        ingredient.prices.append(
            IngredientPrice(price_per_unit=Decimal("1.10"), unit="kg", year=2024)
        )
        session.add(ingredient)
        session.flush()
        ingredient_id = ingredient.id

    with session_scope(session_factory) as session:
        best = price_service.find_best_price(session, ingredient_id, year=2026)
        assert best.price_per_unit == Decimal("1.10")


def test_missing_price_ingredients_lists_ingredients_without_any_price(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Salz", normalized_name="salz", default_unit="kg"))
        priced = Ingredient(name="Zucker", normalized_name="zucker", default_unit="kg")
        priced.prices.append(IngredientPrice(price_per_unit=Decimal("0.99"), unit="kg", year=2026))
        session.add(priced)

    with session_scope(session_factory) as session:
        missing = price_service.missing_price_ingredients(session)
        assert [i.name for i in missing] == ["Salz"]


def test_copy_prices_from_year_fills_ingredients_missing_target_year_price(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Butter", normalized_name="butter", default_unit="kg")
        ingredient.prices.append(IngredientPrice(price_per_unit=Decimal("3.00"), unit="kg", year=2025, source="Preisliste 2025"))
        session.add(ingredient)

    with session_scope(session_factory) as session:
        copied = price_service.copy_prices_from_year(session, source_year=2025, target_year=2026)
        assert copied == 1

    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient).where(Ingredient.normalized_name == "butter")).scalar_one()
        prices_by_year = {price.year: price.price_per_unit for price in ingredient.prices}
        assert prices_by_year[2026] == Decimal("3.00")
