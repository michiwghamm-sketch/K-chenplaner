from __future__ import annotations

import os
import secrets

from flask import Flask, abort, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import select

from app.config import AppConfig
from app.db import initialize_database, session_scope
from app.models import CampYear, ShoppingList, ShoppingListItem
from app.services import shopping_service

SESSION_KEY = "eingeloggt"


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

    @app.template_filter("menge")
    def format_quantity(value) -> str:
        if value is None:
            return ""
        text = f"{value:.3f}".rstrip("0").rstrip(".")
        return text or "0"

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
            groups = shopping_service.grouped_by_store_ordered(shopping_list)
            groups_view = [
                {
                    "store": store or shopping_service.UNASSIGNED_STORE_LABEL,
                    "positionen": sorted(items, key=lambda item: (item.status == "gekauft", (item.ingredient.name if item.ingredient else "").lower())),
                }
                for store, items in groups
            ]
            total_items = len(shopping_list.items)
            bought_items = sum(1 for item in shopping_list.items if item.status == "gekauft")
            return render_template(
                "list_detail.html",
                shopping_list=shopping_list,
                groups=groups_view,
                total_items=total_items,
                bought_items=bought_items,
            )

    @app.post("/position/<int:item_id>/umschalten")
    def toggle_item(item_id: int):
        with session_scope(session_factory) as db_session:
            item = db_session.get(ShoppingListItem, item_id)
            if item is None:
                abort(404)
            new_status = "offen" if item.status == "gekauft" else "gekauft"
            shopping_service.set_item_status(item, new_status)
            db_session.flush()
            return jsonify({"id": item.id, "status": new_status})

    @app.get("/manifest.webmanifest")
    def manifest():
        return app.send_static_file("manifest.webmanifest")

    return app
