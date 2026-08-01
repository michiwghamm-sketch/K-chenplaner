from __future__ import annotations

from datetime import date

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import CampYear
from app.services import shopping_service
from mobile_web.server import create_app


def _make_config(tmp_path):
    return AppConfig.load(project_root=tmp_path, database_path=tmp_path / "mobile_test.sqlite3")


def _seed_shopping_list(config) -> int:
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        camp_year = session.get(CampYear, 1)
        if camp_year is None:
            from decimal import Decimal

            from app.models import Ingredient, MealPlanEntry, Recipe, RecipeIngredient

            ingredient = Ingredient(name="Nudeln", normalized_name="nudeln", default_unit="kg")
            recipe = Recipe(name="Spaghetti", normalized_name="spaghetti", meal_type="Hauptgericht", default_portions=10)
            recipe.ingredients.append(
                RecipeIngredient(ingredient=ingredient, quantity=Decimal("0.100"), unit="kg", price_unit="kg", sort_order=1)
            )
            camp_year = CampYear(year=2026, name="Zeltlager 2026")
            camp_year.meal_plan_entries.append(
                MealPlanEntry(
                    meal_date=date(2026, 8, 2),
                    meal_type="Mittagessen",
                    recipe=recipe,
                    planned_portions=20,
                    status="geplant",
                )
            )
            session.add(camp_year)
            session.flush()
        shopping_list = shopping_service.generate_shopping_list(session, camp_year, assign_shopping_dates=False)
        session.flush()
        return shopping_list.id


def test_list_detail_shows_items_without_pin(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    response = client.get(f"/liste/{list_id}")
    assert response.status_code == 200
    assert "Nudeln".encode() in response.data


def test_login_required_when_pin_set(tmp_path, monkeypatch):
    monkeypatch.setenv("MOBILE_WEB_PIN", "1234")
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    protected = client.get(f"/liste/{list_id}", follow_redirects=False)
    assert protected.status_code == 302
    assert "/login" in protected.headers["Location"]

    wrong_pin = client.post("/login", data={"pin": "0000"})
    assert wrong_pin.status_code == 401

    right_pin = client.post("/login", data={"pin": "1234"}, follow_redirects=True)
    assert right_pin.status_code == 200

    now_allowed = client.get(f"/liste/{list_id}")
    assert now_allowed.status_code == 200
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)


def test_toggle_item_updates_status(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    detail = client.get(f"/liste/{list_id}")
    assert b'data-item-id="1"' in detail.data

    toggled = client.post("/position/1/umschalten")
    assert toggled.status_code == 200
    assert toggled.get_json()["status"] == "gekauft"

    toggled_back = client.post("/position/1/umschalten")
    assert toggled_back.get_json()["status"] == "offen"
