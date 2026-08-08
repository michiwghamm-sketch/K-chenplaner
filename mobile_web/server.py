from __future__ import annotations

import os
import secrets
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select

from app.config import AppConfig
from app.db import initialize_database, session_scope
from app.models import CampYear, ShoppingList, ShoppingListItemAllocation, ShoppingTrip, ingredient_category_sort_key
from app.services import ingredient_service, shopping_service

SESSION_KEY = "eingeloggt"


def _plannable_view(shopping_list: ShoppingList) -> list[dict]:
    return [
        {
            "group_key": index,
            "ingredient_id": group.ingredient_id if group.ingredient_id is not None else "",
            "unit": group.unit,
            "name": group.ingredient_name,
            "remaining": shopping_service.format_quantity_de(group.remaining_quantity),
            "remaining_raw": str(group.remaining_quantity),
        }
        for index, group in enumerate(shopping_service.items_available_for_planning(shopping_list))
    ]


def _trips_view(shopping_list: ShoppingList) -> list[dict]:
    trips = sorted(shopping_list.trips, key=lambda t: (t.store.lower(), t.planned_date is None, t.planned_date, t.created_at))
    labels: list[dict] = []
    for trip in trips:
        label = trip.store
        if trip.planned_date:
            label = f"{label} am {trip.planned_date.strftime('%d.%m.%Y')}"
        labels.append({"id": trip.id, "label": label})
    return labels


def _sorted_trip_allocations(trip: ShoppingTrip) -> list[ShoppingListItemAllocation]:
    return sorted(
        trip.allocations,
        key=lambda a: (
            a.status == "gekauft",
            ingredient_category_sort_key(a.ingredient.category if a.ingredient else None),
            (a.ingredient.name if a.ingredient else "").lower(),
        ),
    )


def create_app(config: AppConfig | None = None) -> Flask:
    """Erstellt die mobile Einkaufslisten-Ansicht als eigenstaendige Flask-App.

    Nutzt dieselbe Cloud-Datenbank wie die Desktop-App (ueber DATABASE_URL) - kein eigenes
    Datenmodell, keine eigene Synchronisation. Gedacht als schlanke Zusatzansicht furs Handy,
    nicht als Ersatz fuer die Desktop-App.
    """
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

    pin = os.environ.get("MOBILE_WEB_PIN")
    app.config["MOBILE_WEB_PIN"] = pin

    database_url = os.environ.get("DATABASE_URL")
    resolved_config = config or AppConfig.load(database_url=database_url)
    if not database_url and resolved_config.is_sqlite:
        app.logger.warning(
            "DATABASE_URL nicht gesetzt - die mobile Ansicht laeuft gegen die lokale SQLite-Datei "
            "statt gegen die geteilte Cloud-Datenbank. Fuer den echten Einsatz DATABASE_URL auf den "
            "Neon-Connection-String setzen."
        )

    _, _engine, session_factory = initialize_database(resolved_config)
    app.config["SESSION_FACTORY"] = session_factory

    app.add_template_filter(shopping_service.format_quantity_de, name="menge")
    app.jinja_env.globals["allocation_recipes"] = lambda allocation: shopping_service.ingredient_linked_recipes(
        allocation.shopping_list, allocation.ingredient_id, allocation.unit
    )
    app.jinja_env.globals["allocation_need_summary"] = lambda allocation: shopping_service.need_purchase_remaining_summary(
        allocation.shopping_list, allocation.ingredient_id, allocation.unit
    )
    app.jinja_env.globals["allocation_requested_by"] = lambda allocation: shopping_service.ingredient_requested_by(
        allocation.shopping_list, allocation.ingredient_id, allocation.unit
    )

    def _require_login():
        if not app.config["MOBILE_WEB_PIN"]:
            return None
        if session.get(SESSION_KEY):
            return None
        return redirect(url_for("login", next=request.path))

    @app.before_request
    def _check_login():
        if request.endpoint in ("login", "login_submit", "static", "manifest"):
            return None
        return _require_login()

    @app.get("/login")
    def login():
        return render_template("login.html", error=None)

    @app.post("/login")
    def login_submit():
        entered = request.form.get("pin", "")
        expected = app.config["MOBILE_WEB_PIN"] or ""
        if expected and secrets.compare_digest(entered, expected):
            session[SESSION_KEY] = True
            session.permanent = True
            next_path = request.args.get("next") or url_for("index")
            return redirect(next_path)
        return render_template("login.html", error="Falscher PIN."), 401

    @app.get("/logout")
    def logout():
        session.pop(SESSION_KEY, None)
        return redirect(url_for("login"))

    @app.get("/")
    def index():
        with session_scope(session_factory) as db_session:
            latest_list = db_session.execute(
                select(ShoppingList).join(CampYear).order_by(CampYear.year.desc(), ShoppingList.generated_at.desc())
            ).scalars().first()
            latest_list_id = latest_list.id if latest_list else None
        if latest_list_id is None:
            return redirect(url_for("all_lists"))
        return redirect(url_for("list_detail", list_id=latest_list_id))

    @app.get("/listen")
    def all_lists():
        with session_scope(session_factory) as db_session:
            camp_years = db_session.execute(
                select(CampYear).order_by(CampYear.year.desc())
            ).scalars().all()
            lists_by_year = [
                {
                    "label": camp_year.name or camp_year.year,
                    "shopping_lists": [
                        {"id": sl.id, "name": sl.name, "item_count": len(sl.items)}
                        for sl in sorted(camp_year.shopping_lists, key=lambda sl: sl.generated_at, reverse=True)
                    ],
                }
                for camp_year in camp_years
                if camp_year.shopping_lists
            ]
            return render_template("lists.html", lists_by_year=lists_by_year)

    @app.get("/liste/<int:list_id>")
    def list_detail(list_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)
            # Altdaten (item.store/item.status aus der Zeit vor Trips/Allocations) einmalig
            # uebernehmen, bevor die Haendler-Gruppierung sie braucht.
            shopping_service.migrate_legacy_store_status(db_session, shopping_list)

            current_person = request.args.get("person") or None
            current_store = request.args.get("store") or None
            sort_mode = request.args.get("sort") or "category"
            persons = [name for name, _ in shopping_service.grouped_by_person_ordered(shopping_list) if name]

            groups = shopping_service.grouped_by_store_ordered_allocations(shopping_list)
            stores = [store for store, _ in groups]

            groups_view = []
            all_shown_allocations = []
            for store, allocations in groups:
                if current_store and store != current_store:
                    continue
                if current_person:
                    allocations = [a for a in allocations if a.assigned_to == current_person]
                if not allocations:
                    continue
                trip_ids = sorted({allocation.shopping_trip_id for allocation in allocations})
                planned_dates = sorted({a.trip.planned_date for a in allocations if a.trip.planned_date})
                if sort_mode == "name":
                    sort_key = lambda a: (a.ingredient.name if a.ingredient else "").lower()  # noqa: E731
                else:
                    sort_key = lambda a: (  # noqa: E731
                        a.status == "gekauft",
                        ingredient_category_sort_key(a.ingredient.category if a.ingredient else None),
                        (a.ingredient.name if a.ingredient else "").lower(),
                    )
                sorted_allocations = sorted(allocations, key=sort_key)
                all_shown_allocations.extend(sorted_allocations)
                groups_view.append(
                    {
                        "store": store,
                        "trip_ids": trip_ids,
                        "planned_date_text": ", ".join(d.strftime("%d.%m.%Y") for d in planned_dates) or None,
                        "positionen": sorted_allocations,
                    }
                )

            total_items = len(all_shown_allocations)
            bought_items = sum(1 for allocation in all_shown_allocations if allocation.status == "gekauft")
            return render_template(
                "list_detail.html",
                shopping_list=shopping_list,
                groups=groups_view,
                total_items=total_items,
                bought_items=bought_items,
                persons=persons,
                current_person=current_person,
                stores=stores,
                current_store=current_store,
                sort_mode=sort_mode,
            )

    @app.get("/liste/<int:list_id>/status")
    def list_status(list_id: int):
        """Schlanker JSON-Endpunkt fuer das Live-Polling in list_detail.html - liefert nur die
        veraenderlichen Felder (Status/Person/Kaufmenge), damit mehrere Leute, die gleichzeitig
        im selben Laden abhaken, sich gegenseitig auf dem Schirm sehen, ohne manuell neu zu laden."""
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)
            current_person = request.args.get("person") or None
            current_store = request.args.get("store") or None
            allocations = shopping_list.allocations
            if current_person:
                allocations = [a for a in allocations if a.assigned_to == current_person]
            if current_store:
                allocations = [a for a in allocations if a.trip.store == current_store]
            return jsonify(
                {
                    "positionen": [
                        {
                            "id": allocation.id,
                            "status": allocation.status,
                            "assigned_to": allocation.assigned_to,
                            "purchased_quantity": str(allocation.purchased_quantity)
                            if allocation.purchased_quantity is not None
                            else None,
                            "purchased_at_text": shopping_service.format_date_de(allocation.purchased_at.date())
                            if allocation.purchased_at
                            else None,
                        }
                        for allocation in allocations
                    ]
                }
            )

    @app.post("/position/<int:allocation_id>/umschalten")
    def toggle_allocation(allocation_id: int):
        with session_scope(session_factory) as db_session:
            allocation = db_session.get(ShoppingListItemAllocation, allocation_id)
            if allocation is None:
                abort(404)
            if allocation.status == "gekauft":
                shopping_service.mark_allocation_open(allocation)
            else:
                purchased_quantity = None
                raw_quantity = request.form.get("purchased_quantity")
                if raw_quantity:
                    try:
                        purchased_quantity = Decimal(raw_quantity)
                    except InvalidOperation:
                        abort(400)
                shopping_service.mark_allocation_purchased(allocation, purchased_quantity)
            db_session.flush()
            return jsonify(
                {
                    "id": allocation.id,
                    "status": allocation.status,
                    "purchased_quantity": str(allocation.purchased_quantity) if allocation.purchased_quantity is not None else None,
                    "purchased_at": allocation.purchased_at.isoformat() if allocation.purchased_at else None,
                    "purchased_at_text": shopping_service.format_date_de(allocation.purchased_at.date())
                    if allocation.purchased_at
                    else None,
                }
            )

    @app.get("/liste/<int:list_id>/einkauf-planen")
    def plan_trip_form(list_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)
            return render_template(
                "plan_trip.html", shopping_list=shopping_list, plannable=_plannable_view(shopping_list), error=None
            )

    @app.post("/liste/<int:list_id>/einkauf-planen")
    def plan_trip_submit(list_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)

            store = (request.form.get("store") or "").strip()
            participants = [name.strip() for name in (request.form.get("teilnehmer") or "").split(",") if name.strip()]
            raw_planned_date = request.form.get("einkaufstag") or ""
            try:
                planned_date = date.fromisoformat(raw_planned_date) if raw_planned_date else None
            except ValueError:
                planned_date = None
            selections = []
            for group_key in request.form.getlist("position"):
                raw_ingredient_id = request.form.get(f"ingredient_id_{group_key}", "")
                ingredient_id = int(raw_ingredient_id) if raw_ingredient_id else None
                unit = request.form.get(f"unit_{group_key}", "")
                raw_quantity = request.form.get(f"menge_{group_key}")
                try:
                    quantity = Decimal(raw_quantity) if raw_quantity else None
                except InvalidOperation:
                    quantity = None
                if quantity is None or quantity <= 0:
                    continue
                selections.append((ingredient_id, unit, quantity))

            try:
                shopping_service.create_shopping_trip(
                    db_session,
                    shopping_list,
                    store=store,
                    participants=participants,
                    selections=selections,
                    planned_date=planned_date,
                )
            except ValueError as exc:
                return (
                    render_template(
                        "plan_trip.html", shopping_list=shopping_list, plannable=_plannable_view(shopping_list), error=str(exc)
                    ),
                    400,
                )

        return redirect(url_for("list_detail", list_id=list_id))

    @app.get("/liste/<int:list_id>/position-hinzufuegen")
    def add_manual_item_form(list_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)
            ingredient_names = [i.name for i in ingredient_service.search_ingredients(db_session, active_only=False)]
            return render_template(
                "add_item.html",
                shopping_list=shopping_list,
                ingredient_names=ingredient_names,
                trips=_trips_view(shopping_list),
                error=None,
            )

    @app.post("/liste/<int:list_id>/position-hinzufuegen")
    def add_manual_item_submit(list_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)

            name = (request.form.get("name") or "").strip()
            unit = (request.form.get("unit") or "").strip() or None
            requested_by = (request.form.get("gewuenscht_von") or "").strip() or None
            raw_quantity = request.form.get("menge")
            raw_trip_id = request.form.get("trip_id")
            try:
                quantity = Decimal(raw_quantity) if raw_quantity else None
            except InvalidOperation:
                quantity = None
            trip = None
            if raw_trip_id:
                trip = db_session.get(ShoppingTrip, int(raw_trip_id))
                if trip is not None and trip.shopping_list_id != list_id:
                    trip = None

            error = None
            if not name:
                error = "Bitte einen Namen eingeben."
            elif quantity is None or quantity <= 0:
                error = "Bitte eine gültige Menge eingeben."

            if error:
                ingredient_names = [i.name for i in ingredient_service.search_ingredients(db_session, active_only=False)]
                return (
                    render_template(
                        "add_item.html",
                        shopping_list=shopping_list,
                        ingredient_names=ingredient_names,
                        trips=_trips_view(shopping_list),
                        error=error,
                    ),
                    400,
                )

            ingredient = ingredient_service.find_or_create_ingredient(db_session, name=name, default_unit=unit)
            item = shopping_service.add_manual_shopping_item(
                db_session, shopping_list, ingredient=ingredient, quantity=quantity, unit=unit, requested_by=requested_by
            )
            if trip is not None:
                # Sonderwunsch direkt einem bestehenden geplanten Einkauf zuteilen, statt dass er
                # erst unzugeteilt in der Liste haengt und separat ueber "Einkauf planen"/
                # "Einkauf bearbeiten" nachtraeglich zugeteilt werden muss.
                try:
                    shopping_service.add_allocations_to_trip(db_session, trip, [(ingredient.id, item.unit, quantity)])
                except ValueError:
                    pass

        return redirect(url_for("list_detail", list_id=list_id))

    @app.post("/liste/<int:list_id>/haendler/<store>/neu-mischen")
    def reshuffle_store(list_id: int, store: str):
        participants_raw = request.form.get("teilnehmer")
        participants = None
        if participants_raw is not None:
            participants = [name.strip() for name in participants_raw.split(",") if name.strip()]
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)
            for trip in shopping_list.trips:
                if trip.store == store:
                    shopping_service.reshuffle_trip_assignments(trip, participants)
        return redirect(
            url_for(
                "list_detail",
                list_id=list_id,
                store=request.args.get("return_store") or None,
                person=request.args.get("person") or None,
                sort=request.args.get("sort") or None,
            )
        )

    @app.get("/liste/<int:list_id>/einkauf/<int:trip_id>/bearbeiten")
    def edit_trip_form(list_id: int, trip_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            trip = db_session.get(ShoppingTrip, trip_id)
            if shopping_list is None or trip is None or trip.shopping_list_id != list_id:
                abort(404)
            return render_template(
                "edit_trip.html",
                shopping_list=shopping_list,
                trip=trip,
                allocations=_sorted_trip_allocations(trip),
                plannable=_plannable_view(shopping_list),
                error=None,
            )

    @app.post("/liste/<int:list_id>/einkauf/<int:trip_id>/bearbeiten")
    def edit_trip_submit(list_id: int, trip_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            trip = db_session.get(ShoppingTrip, trip_id)
            if shopping_list is None or trip is None or trip.shopping_list_id != list_id:
                abort(404)

            selections = []
            for group_key in request.form.getlist("position"):
                raw_ingredient_id = request.form.get(f"ingredient_id_{group_key}", "")
                ingredient_id = int(raw_ingredient_id) if raw_ingredient_id else None
                unit = request.form.get(f"unit_{group_key}", "")
                raw_quantity = request.form.get(f"menge_{group_key}")
                try:
                    quantity = Decimal(raw_quantity) if raw_quantity else None
                except InvalidOperation:
                    quantity = None
                if quantity is None or quantity <= 0:
                    continue
                selections.append((ingredient_id, unit, quantity))

            error = None
            if not selections:
                error = "Bitte mindestens eine Position mit Menge auswählen."
            else:
                try:
                    shopping_service.add_allocations_to_trip(db_session, trip, selections)
                except ValueError as exc:
                    error = str(exc)

            if error:
                return (
                    render_template(
                        "edit_trip.html",
                        shopping_list=shopping_list,
                        trip=trip,
                        allocations=_sorted_trip_allocations(trip),
                        plannable=_plannable_view(shopping_list),
                        error=error,
                    ),
                    400,
                )

        return redirect(url_for("edit_trip_form", list_id=list_id, trip_id=trip_id))

    @app.post("/liste/<int:list_id>/einkauf/<int:trip_id>/position/<int:allocation_id>/entfernen")
    def remove_trip_position(list_id: int, trip_id: int, allocation_id: int):
        with session_scope(session_factory) as db_session:
            allocation = db_session.get(ShoppingListItemAllocation, allocation_id)
            if allocation is None or allocation.shopping_trip_id != trip_id:
                abort(404)
            shopping_service.delete_allocation(db_session, allocation)
        # Von der Suche aus aufgerufen: dahin zurueck statt auf die (dort gar nicht sichtbare)
        # Einkauf-bearbeiten-Seite.
        if request.form.get("from_search"):
            return redirect(url_for("search_ingredients", list_id=list_id, q=request.form.get("q") or ""))
        return redirect(url_for("edit_trip_form", list_id=list_id, trip_id=trip_id))

    @app.post("/liste/<int:list_id>/einkauf/<int:trip_id>/loeschen")
    def delete_trip(list_id: int, trip_id: int):
        with session_scope(session_factory) as db_session:
            trip = db_session.get(ShoppingTrip, trip_id)
            if trip is None or trip.shopping_list_id != list_id:
                abort(404)
            shopping_service.delete_shopping_trip(db_session, trip)
        return redirect(url_for("list_detail", list_id=list_id))

    @app.get("/liste/<int:list_id>/suche")
    def search_ingredients(list_id: int):
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)
            query = (request.args.get("q") or "").strip()

            results = []
            if query:
                normalized_query = query.lower()
                seen_keys: set[tuple[int | None, str]] = set()
                for item in shopping_list.items:
                    if item.ingredient is None or normalized_query not in item.ingredient.name.lower():
                        continue
                    key = (item.ingredient_id, item.unit or "")
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    ingredient_id, unit = key
                    needed, _purchased, _remaining, _history = shopping_service.need_purchase_remaining_summary(
                        shopping_list, ingredient_id, unit
                    )
                    plannable = shopping_service.plannable_quantity_for_ingredient(shopping_list, ingredient_id, unit)
                    allocations = [
                        {
                            "id": a.id,
                            "trip_id": a.shopping_trip_id,
                            "store": a.trip.store,
                            "quantity": shopping_service.format_quantity_de(a.quantity),
                            "status": a.status,
                        }
                        for a in shopping_list.allocations
                        if (a.ingredient_id, a.unit or "") == key
                    ]
                    results.append(
                        {
                            "ingredient_id": ingredient_id,
                            "unit": unit,
                            "name": item.ingredient.name,
                            "category": item.ingredient.category,
                            "needed": shopping_service.format_quantity_de(needed),
                            "plannable_raw": str(plannable),
                            "plannable_text": shopping_service.format_quantity_de(plannable),
                            "allocations": allocations,
                        }
                    )
                results.sort(key=lambda r: r["name"].lower())

            return render_template(
                "search.html",
                shopping_list=shopping_list,
                query=query,
                results=results,
                trips=_trips_view(shopping_list),
            )

    @app.post("/liste/<int:list_id>/suche/hinzufuegen")
    def add_to_trip_from_search(list_id: int):
        query = request.form.get("q") or ""
        with session_scope(session_factory) as db_session:
            shopping_list = db_session.get(ShoppingList, list_id)
            if shopping_list is None:
                abort(404)

            raw_trip_id = request.form.get("trip_id")
            raw_ingredient_id = request.form.get("ingredient_id")
            unit = request.form.get("unit") or ""
            raw_quantity = request.form.get("menge")
            try:
                trip_id = int(raw_trip_id) if raw_trip_id else None
                ingredient_id = int(raw_ingredient_id) if raw_ingredient_id else None
                quantity = Decimal(raw_quantity) if raw_quantity else None
            except (InvalidOperation, ValueError):
                trip_id = None
                ingredient_id = None
                quantity = None

            trip = db_session.get(ShoppingTrip, trip_id) if trip_id else None
            if trip is not None and trip.shopping_list_id != list_id:
                trip = None

            if trip is not None and ingredient_id is not None and quantity is not None and quantity > 0:
                try:
                    shopping_service.add_allocations_to_trip(db_session, trip, [(ingredient_id, unit, quantity)])
                except ValueError:
                    pass

        return redirect(url_for("search_ingredients", list_id=list_id, q=query))

    @app.get("/manifest.webmanifest")
    def manifest():
        return app.send_static_file("manifest.webmanifest")

    return app
