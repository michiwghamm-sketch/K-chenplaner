from decimal import Decimal

from sqlalchemy import select

from app.db import session_scope
from app.models import Ingredient, IngredientPrice
from app.services import open_prices_service, price_service


def test_auto_import_open_prices_adds_price_for_missing_ingredient(session_factory, monkeypatch) -> None:
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg"))

    def fake_import_price_for_ingredient(
        ingredient_id: int,
        ingredient_name: str,
        *,
        target_unit: str | None,
        year: int,
        currency: str | None = "EUR",
        notes_prefix: str | None = None,
        timeout: int = 15,
    ):
        price = IngredientPrice(
            ingredient_id=ingredient_id,
            price_per_unit=Decimal("2.40"),
            unit="kg",
            source="Open Prices",
            year=year,
            notes="Testimport",
        )
        return open_prices_service.OpenPricesImportResult(
            ingredient_id=ingredient_id,
            ingredient_name=ingredient_name,
            year=year,
            status="imported",
            message="Nudeln (123)",
            price_record=price,
        )

    monkeypatch.setattr(open_prices_service, "import_price_for_ingredient", fake_import_price_for_ingredient)

    with session_scope(session_factory) as session:
        missing = price_service.missing_price_ingredients(session, year=2026)
        for ingredient in missing:
            result = open_prices_service.import_price_for_ingredient(
                ingredient.id,
                ingredient.name,
                target_unit=ingredient.default_unit,
                year=2026,
            )
            if result.price_record is not None:
                session.add(result.price_record)

    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient).where(Ingredient.normalized_name == "nudeln")).scalar_one()
        assert len(ingredient.prices) == 1
        assert ingredient.prices[0].price_per_unit == Decimal("2.40")
