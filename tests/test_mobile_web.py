from __future__ import annotations

from datetime import date
from decimal import Decimal

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


def _seed_shopping_list_with_trip(config, *, store: str = "Edeka", participants: list[str] | None = None) -> tuple[int, int]:
    """Wie _seed_shopping_list, plant aber sofort einen Einkauf fuer die volle Menge -
    fuer Tests, die eine sichtbare Allocation brauchen (Mobile zeigt nur Geplantes an)."""
    list_id = _seed_shopping_list(config)
    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingList

        shopping_list = session.get(ShoppingList, list_id)
        item = shopping_list.items[0]
        remaining = shopping_service.remaining_quantity_for_ingredient(shopping_list, item.ingredient_id, item.unit)
        trip = shopping_service.create_shopping_trip(
            session,
            shopping_list,
            store=store,
            participants=participants or [],
            selections=[(item.ingredient_id, item.unit, remaining)],
        )
        session.flush()
        return list_id, trip.allocations[0].id


def test_list_detail_shows_items_from_planned_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, _ = _seed_shopping_list_with_trip(config)

    app = create_app(config=config)
    client = app.test_client()

    response = client.get(f"/liste/{list_id}")
    assert response.status_code == 200
    assert "Nudeln".encode() in response.data
    assert "Edeka".encode() in response.data


def test_list_detail_shows_empty_state_when_nothing_planned(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    response = client.get(f"/liste/{list_id}")
    assert response.status_code == 200
    assert "Noch nichts geplant".encode() in response.data


def test_login_required_when_pin_set(tmp_path, monkeypatch):
    monkeypatch.setenv("MOBILE_WEB_PIN", "1234")
    config = _make_config(tmp_path)
    list_id, _ = _seed_shopping_list_with_trip(config)

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


def test_all_lists_page_renders(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/listen")
    assert response.status_code == 200
    assert "Zeltlager 2026".encode() in response.data


def test_toggle_allocation_captures_purchased_quantity(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config)

    app = create_app(config=config)
    client = app.test_client()

    detail = client.get(f"/liste/{list_id}")
    assert f'data-allocation-id="{allocation_id}"'.encode() in detail.data

    toggled = client.post(f"/position/{allocation_id}/umschalten", data={"purchased_quantity": "1.5"})
    assert toggled.status_code == 200
    body = toggled.get_json()
    assert body["status"] == "gekauft"
    assert body["purchased_quantity"] == "1.5"

    toggled_back = client.post(f"/position/{allocation_id}/umschalten")
    assert toggled_back.get_json()["status"] == "offen"


def test_plan_trip_form_and_submit_creates_allocation(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    form = client.get(f"/liste/{list_id}/einkauf-planen")
    assert form.status_code == 200
    assert "Nudeln".encode() in form.data

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingList

        shopping_list = session.get(ShoppingList, list_id)
        item = shopping_list.items[0]
        ingredient_id = item.ingredient_id
        unit = item.unit

    submit = client.post(
        f"/liste/{list_id}/einkauf-planen",
        data={
            "store": "Metro",
            "teilnehmer": "Anna, Ben",
            "position": ["0"],
            "ingredient_id_0": str(ingredient_id),
            "unit_0": unit,
            "menge_0": "1.0",
        },
        follow_redirects=True,
    )
    assert submit.status_code == 200
    assert "Metro".encode() in submit.data


def test_person_filter_shows_only_assigned_allocations(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, _ = _seed_shopping_list_with_trip(config, participants=["Anna"])

    app = create_app(config=config)
    client = app.test_client()

    for_anna = client.get(f"/liste/{list_id}?person=Anna")
    assert for_anna.status_code == 200
    assert "Nudeln".encode() in for_anna.data

    for_ben = client.get(f"/liste/{list_id}?person=Ben")
    assert for_ben.status_code == 200
    assert "keine Positionen eingeteilt".encode() in for_ben.data


def test_reshuffle_store_updates_assignment(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Metro", participants=["Anna"])

    app = create_app(config=config)
    client = app.test_client()

    response = client.post(f"/liste/{list_id}/haendler/Metro/neu-mischen", data={"teilnehmer": "Ben, Chris"}, follow_redirects=True)
    assert response.status_code == 200

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingListItemAllocation

        allocation = session.get(ShoppingListItemAllocation, allocation_id)
        assert allocation.assigned_to in ("Ben", "Chris")
