from decimal import Decimal

import pytest
from sqlalchemy import select

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import Ingredient, IngredientPrice


@pytest.fixture()
def session_factory(tmp_path):
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "prices.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    return create_session_factory(engine)


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
