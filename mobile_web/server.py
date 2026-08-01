from __future__ import annotations

import os
import secrets
from decimal import Decimal, InvalidOperation

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select

from app.config import AppConfig
from app.db import initialize_database, session_scope
from app.models import CampYear, ShoppingList, ShoppingListItemAllocation
from app.services import shopping_service

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
            persons = [name for name, _ in shopping_service.grouped_by_person_ordered(shopping_list) if name]

            groups = shopping_service.grouped_by_store_ordered_allocations(shopping_list)
            groups_view = []
            all_shown_allocations = []
            for store, allocations in groups:
                if current_person:
                    allocations = [a for a in allocations if a.assigned_to == current_person]
                if not allocations:
                    continue
                trip_ids = sorted({allocation.shopping_trip_id for allocation in allocations})
                sorted_allocations = sorted(
                    allocations,
                    key=lambda a: (a.status == "gekauft", (a.ingredient.name if a.ingredient else "").lower()),
                )
                all_shown_allocations.extend(sorted_allocations)
                groups_view.append({"store": store, "trip_ids": trip_ids, "positionen": sorted_allocations})

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
                    db_session, shopping_list, store=store, participants=participants, selections=selections
                )
            except ValueError as exc:
                return (
                    render_template(
                        "plan_trip.html", shopping_list=shopping_list, plannable=_plannable_view(shopping_list), error=str(exc)
                    ),
                    400,
                )

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
        return redirect(url_for("list_detail", list_id=list_id))

    @app.get("/manifest.webmanifest")
    def manifest():
        return app.send_static_file("manifest.webmanifest")

    return app
