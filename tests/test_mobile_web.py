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
    assert body["purchased_at"] is not None
    assert body["purchased_at_text"]

    detail_after_toggle = client.get(f"/liste/{list_id}")
    assert "gekauft: 1.5 kg".encode() in detail_after_toggle.data
    assert "Rest benötigt".encode() in detail_after_toggle.data

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
            "einkaufstag": "2026-08-05",
            "position": ["0"],
            "ingredient_id_0": str(ingredient_id),
            "unit_0": unit,
            "menge_0": "1.0",
        },
        follow_redirects=True,
    )
    assert submit.status_code == 200
    assert "Metro".encode() in submit.data
    assert "05.08.2026".encode() in submit.data

    with session_scope(session_factory) as session:
        from app.models import ShoppingTrip

        trip = session.query(ShoppingTrip).filter_by(store="Metro").one()
        assert trip.planned_date == date(2026, 8, 5)


def test_store_filter_shows_only_selected_store(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import Ingredient, ShoppingList

        shopping_list = session.get(ShoppingList, list_id)
        item = shopping_list.items[0]
        remaining = shopping_service.remaining_quantity_for_ingredient(shopping_list, item.ingredient_id, item.unit)
        shopping_service.create_shopping_trip(
            session,
            shopping_list,
            store="Edeka",
            participants=[],
            selections=[(item.ingredient_id, item.unit, remaining)],
        )
        sonnencreme = Ingredient(name="Sonnencreme", normalized_name="sonnencreme", default_unit="Stk")
        session.add(sonnencreme)
        session.flush()
        shopping_service.add_manual_shopping_item(
            session, shopping_list, ingredient=sonnencreme, quantity=Decimal("1"), unit="Stk"
        )
        shopping_service.create_shopping_trip(
            session, shopping_list, store="Metro", participants=[], selections=[(sonnencreme.id, "Stk", Decimal("1"))]
        )

    app = create_app(config=config)
    client = app.test_client()

    only_edeka = client.get(f"/liste/{list_id}?store=Edeka")
    assert only_edeka.status_code == 200
    assert "Nudeln".encode() in only_edeka.data
    assert "Sonnencreme".encode() not in only_edeka.data

    only_metro = client.get(f"/liste/{list_id}?store=Metro")
    assert only_metro.status_code == 200
    assert "Sonnencreme".encode() in only_metro.data
    assert "Nudeln".encode() not in only_metro.data

    all_stores = client.get(f"/liste/{list_id}")
    assert "Nudeln".encode() in all_stores.data
    assert "Sonnencreme".encode() in all_stores.data


def test_sort_mode_name_orders_alphabetically_across_categories(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import Ingredient, ShoppingList

        shopping_list = session.get(ShoppingList, list_id)
        item = shopping_list.items[0]
        remaining = shopping_service.remaining_quantity_for_ingredient(shopping_list, item.ingredient_id, item.unit)
        # Zwiebel als "Obst" markiert (fachlich falsch, aber fuer den Test wichtig): nach
        # Kategorie sortiert kommt Zwiebel (Obst) VOR Apfel (Trockenware), alphabetisch ist es
        # umgekehrt - so lassen sich beide Sortiermodi eindeutig unterscheiden.
        item.ingredient.category = "Obst"
        apfel = Ingredient(name="Apfel", normalized_name="apfel", default_unit="Stk", category="Trockenware")
        session.add(apfel)
        session.flush()
        shopping_service.add_manual_shopping_item(session, shopping_list, ingredient=apfel, quantity=Decimal("1"), unit="Stk")
        shopping_service.create_shopping_trip(
            session,
            shopping_list,
            store="Edeka",
            participants=[],
            selections=[(item.ingredient_id, item.unit, remaining), (apfel.id, "Stk", Decimal("1"))],
        )

    app = create_app(config=config)
    client = app.test_client()

    by_category = client.get(f"/liste/{list_id}?sort=category").data.decode("utf-8")
    assert by_category.index("Nudeln") < by_category.index("Apfel")

    by_name = client.get(f"/liste/{list_id}?sort=name").data.decode("utf-8")
    assert by_name.index("Apfel") < by_name.index("Nudeln")


def test_search_finds_ingredient_and_shows_allocation_with_remove_option(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Edeka")

    app = create_app(config=config)
    client = app.test_client()

    found = client.get(f"/liste/{list_id}/suche?q=Nud")
    assert found.status_code == 200
    assert "Nudeln".encode() in found.data
    assert "Edeka".encode() in found.data

    not_found = client.get(f"/liste/{list_id}/suche?q=xyzxyz")
    assert not_found.status_code == 200
    assert "Keine Zutat gefunden".encode() in not_found.data


def test_search_can_remove_position_and_redirects_back_to_search(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Edeka")

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingListItemAllocation

        trip_id = session.get(ShoppingListItemAllocation, allocation_id).shopping_trip_id

    app = create_app(config=config)
    client = app.test_client()

    response = client.post(
        f"/liste/{list_id}/einkauf/{trip_id}/position/{allocation_id}/entfernen",
        data={"from_search": "1", "q": "Nud"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/suche?" in response.headers["Location"]
    assert "q=Nud" in response.headers["Location"]

    with session_scope(session_factory) as session:
        from app.models import ShoppingListItemAllocation

        assert session.get(ShoppingListItemAllocation, allocation_id) is None


def test_search_can_add_ingredient_to_existing_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingList

        shopping_list = session.get(ShoppingList, list_id)
        item = shopping_list.items[0]
        trip = shopping_service.create_shopping_trip(
            session, shopping_list, store="Edeka", participants=[], selections=[(item.ingredient_id, item.unit, Decimal("1"))]
        )
        trip_id = trip.id
        ingredient_id = item.ingredient_id
        unit = item.unit

    app = create_app(config=config)
    client = app.test_client()

    found = client.get(f"/liste/{list_id}/suche?q=Nud")
    assert found.status_code == 200
    assert "Nudeln".encode() in found.data

    response = client.post(
        f"/liste/{list_id}/suche/hinzufuegen",
        data={"ingredient_id": str(ingredient_id), "unit": unit, "menge": "1", "trip_id": str(trip_id), "q": "Nud"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    with session_scope(session_factory) as session:
        from app.models import ShoppingTrip

        trip = session.get(ShoppingTrip, trip_id)
        # add_allocations_to_trip legt fuer jede Auswahl eine eigene Allocation an, statt mit
        # einer bestehenden fuer dieselbe Zutat zusammenzufuehren (siehe "eine Auswahl = ein
        # Listeneintrag" in ShoppingListItemAllocation).
        assert len(trip.allocations) == 2
        assert sum((a.quantity for a in trip.allocations), Decimal("0")) == Decimal("2.000")


def test_edit_trip_form_shows_current_positions_and_plannable_items(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Edeka")

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingListItemAllocation

        trip_id = session.get(ShoppingListItemAllocation, allocation_id).shopping_trip_id

        from app.models import Ingredient, ShoppingList

        shopping_list = session.get(ShoppingList, list_id)
        sonnencreme = Ingredient(name="Sonnencreme", normalized_name="sonnencreme", default_unit="Stk")
        session.add(sonnencreme)
        session.flush()
        shopping_service.add_manual_shopping_item(
            session, shopping_list, ingredient=sonnencreme, quantity=Decimal("1"), unit="Stk"
        )

    app = create_app(config=config)
    client = app.test_client()

    response = client.get(f"/liste/{list_id}/einkauf/{trip_id}/bearbeiten")
    assert response.status_code == 200
    assert "Nudeln".encode() in response.data
    assert "Sonnencreme".encode() in response.data


def test_edit_trip_submit_adds_position(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Edeka")

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import Ingredient, ShoppingList, ShoppingListItemAllocation

        trip_id = session.get(ShoppingListItemAllocation, allocation_id).shopping_trip_id
        shopping_list = session.get(ShoppingList, list_id)
        sonnencreme = Ingredient(name="Sonnencreme", normalized_name="sonnencreme", default_unit="Stk")
        session.add(sonnencreme)
        session.flush()
        shopping_service.add_manual_shopping_item(
            session, shopping_list, ingredient=sonnencreme, quantity=Decimal("1"), unit="Stk"
        )
        sonnencreme_id = sonnencreme.id

    app = create_app(config=config)
    client = app.test_client()

    response = client.post(
        f"/liste/{list_id}/einkauf/{trip_id}/bearbeiten",
        data={
            "position": ["0"],
            "ingredient_id_0": str(sonnencreme_id),
            "unit_0": "Stk",
            "menge_0": "1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    with session_scope(session_factory) as session:
        from app.models import ShoppingTrip

        trip = session.get(ShoppingTrip, trip_id)
        assert len(trip.allocations) == 2
        assert any(a.ingredient.name == "Sonnencreme" for a in trip.allocations)


def test_remove_trip_position_deletes_allocation(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Edeka")

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingListItemAllocation

        trip_id = session.get(ShoppingListItemAllocation, allocation_id).shopping_trip_id

    app = create_app(config=config)
    client = app.test_client()

    response = client.post(
        f"/liste/{list_id}/einkauf/{trip_id}/position/{allocation_id}/entfernen", follow_redirects=True
    )
    assert response.status_code == 200

    with session_scope(session_factory) as session:
        from app.models import ShoppingListItemAllocation

        assert session.get(ShoppingListItemAllocation, allocation_id) is None


def test_delete_trip_removes_trip_and_allocations(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Edeka")

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingListItemAllocation

        trip_id = session.get(ShoppingListItemAllocation, allocation_id).shopping_trip_id

    app = create_app(config=config)
    client = app.test_client()

    response = client.post(f"/liste/{list_id}/einkauf/{trip_id}/loeschen", follow_redirects=True)
    assert response.status_code == 200

    with session_scope(session_factory) as session:
        from app.models import ShoppingTrip

        assert session.get(ShoppingTrip, trip_id) is None


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


def test_status_endpoint_reflects_toggled_allocation(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, allocation_id = _seed_shopping_list_with_trip(config, store="Metro", participants=["Anna"])

    app = create_app(config=config)
    client = app.test_client()

    before = client.get(f"/liste/{list_id}/status")
    assert before.status_code == 200
    positionen = before.get_json()["positionen"]
    assert len(positionen) == 1
    assert positionen[0]["id"] == allocation_id
    assert positionen[0]["status"] == "offen"
    assert positionen[0]["assigned_to"] == "Anna"

    client.post(f"/position/{allocation_id}/umschalten", data={"purchased_quantity": "2.5"})

    after = client.get(f"/liste/{list_id}/status")
    position = after.get_json()["positionen"][0]
    assert position["status"] == "gekauft"
    assert position["purchased_quantity"] == "2.500"


def test_status_endpoint_respects_person_filter(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, _ = _seed_shopping_list_with_trip(config, participants=["Anna"])

    app = create_app(config=config)
    client = app.test_client()

    for_anna = client.get(f"/liste/{list_id}/status?person=Anna")
    assert len(for_anna.get_json()["positionen"]) == 1

    for_ben = client.get(f"/liste/{list_id}/status?person=Ben")
    assert for_ben.get_json()["positionen"] == []


def test_add_manual_item_form_and_submit(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    form = client.get(f"/liste/{list_id}/position-hinzufuegen")
    assert form.status_code == 200

    submit = client.post(
        f"/liste/{list_id}/position-hinzufuegen",
        data={"name": "Sonnencreme", "menge": "1", "unit": "Stk", "gewuenscht_von": "Björn"},
        follow_redirects=True,
    )
    assert submit.status_code == 200

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingList
        from app.services import shopping_service as shopping_service_module

        shopping_list = session.get(ShoppingList, list_id)
        manual_items = [item for item in shopping_list.items if shopping_service_module.is_manual_item(item)]
        assert len(manual_items) == 1
        assert manual_items[0].ingredient.name == "Sonnencreme"
        assert manual_items[0].requested_by == "Björn"


def test_add_manual_item_form_shows_and_assigns_to_existing_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, _ = _seed_shopping_list_with_trip(config, store="Edeka")

    app = create_app(config=config)
    client = app.test_client()

    form = client.get(f"/liste/{list_id}/position-hinzufuegen")
    assert form.status_code == 200
    assert "Edeka".encode() in form.data
    assert "Direkt einem Einkauf zuordnen".encode() in form.data

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        from app.models import ShoppingTrip

        trip_id = session.query(ShoppingTrip).filter_by(store="Edeka").one().id

    submit = client.post(
        f"/liste/{list_id}/position-hinzufuegen",
        data={"name": "Sonnencreme", "menge": "1", "unit": "Stk", "trip_id": str(trip_id)},
        follow_redirects=True,
    )
    assert submit.status_code == 200

    with session_scope(session_factory) as session:
        from app.models import ShoppingTrip

        trip = session.get(ShoppingTrip, trip_id)
        assert any(a.ingredient.name == "Sonnencreme" for a in trip.allocations)


def test_add_manual_item_submit_rejects_missing_name(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id = _seed_shopping_list(config)

    app = create_app(config=config)
    client = app.test_client()

    response = client.post(
        f"/liste/{list_id}/position-hinzufuegen",
        data={"name": "", "menge": "1", "unit": "Stk"},
    )
    assert response.status_code == 400


def test_service_worker_served_at_root_with_no_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    app = create_app(config=config)
    client = app.test_client()

    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["Content-Type"]
    assert response.headers["Cache-Control"] == "no-cache"


def test_offline_forms_are_marked_for_client_side_interception(tmp_path, monkeypatch):
    """Regressionstest: schreibende Formulare brauchen die Klasse "js-offline-form", damit
    offline.js sie abfangen und bei fehlender Verbindung zwischenspeichern kann (siehe
    mobile_web/static/offline.js). Kein Ersatz fuer echtes Browser-Testing der Offline-Logik,
    stellt aber sicher, dass die Markierung bei Template-Aenderungen nicht versehentlich verloren
    geht."""
    monkeypatch.delenv("MOBILE_WEB_PIN", raising=False)
    config = _make_config(tmp_path)
    list_id, _ = _seed_shopping_list_with_trip(config, store="Edeka")

    app = create_app(config=config)
    client = app.test_client()

    detail = client.get(f"/liste/{list_id}")
    assert 'class="neu-mischen-form js-offline-form"'.encode() in detail.data

    add_item_form = client.get(f"/liste/{list_id}/position-hinzufuegen")
    assert 'class="js-offline-form"'.encode() in add_item_form.data

    plan_trip_form_response = client.get(f"/liste/{list_id}/einkauf-planen")
    assert 'class="js-offline-form"'.encode() in plan_trip_form_response.data
