from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from app.models import (
    CampYear,
    Ingredient,
    ShoppingList,
    ShoppingListItem,
    ShoppingListItemAllocation,
    ShoppingTrip,
    StandardShoppingItem,
)
from app.services import planning_service, price_service


@dataclass(slots=True)
class _Aggregate:
    ingredient_id: int
    unit: str
    shopping_date: date | None
    quantity: Decimal = Decimal("0")
    recipe_names: set[str] = field(default_factory=set)
    needed_dates: set[date] = field(default_factory=set)


def _derive_item_shopping_date(entry, camp_year: CampYear) -> date | None:
    """Automatischer Einkaufstag, wenn am Mahlzeit-Slot keiner manuell gesetzt wurde: ein Tag vor
    der Mahlzeit (moeglichst kurze Lagerzeit)."""
    if entry.meal_date is None:
        return None
    return planning_service.derive_shopping_date(entry.meal_date, days_before=1)


def _estimate_price(session, ingredient_id: int, unit: str, quantity: Decimal, price_year: int) -> tuple[Decimal | None, Decimal | None]:
    best_price = price_service.find_best_price(session, ingredient_id, year=price_year, fallback_latest=False)
    if not best_price or not price_service.can_convert_units(best_price.unit, unit):
        return None, None
    estimated_price_per_unit = price_service.convert_price_per_unit(
        best_price.price_per_unit, from_unit=best_price.unit, to_unit=unit
    ).quantize(Decimal("0.0001"))
    estimated_total = (quantity * estimated_price_per_unit).quantize(Decimal("0.01"))
    return estimated_price_per_unit, estimated_total


def _aggregate_recipe_items(camp_year: CampYear, *, assign_shopping_dates: bool) -> dict[tuple[int, str, date | None], _Aggregate]:
    """Aggregiert alle geplanten (nicht abgesagten) Mahlzeiten eines Camp-Jahrs zu Zutat+Einheit+
    Einkaufstag-Bedarfsmengen - gemeinsam genutzt von generate_shopping_list() (neue Liste) und
    update_shopping_list_from_meal_plan() (bestehende Liste an den aktuellen Wochenplan anpassen),
    damit beide exakt dieselbe Mengenberechnung verwenden."""
    aggregates: dict[tuple[int, str, date | None], _Aggregate] = {}
    for entry in camp_year.meal_plan_entries:
        if entry.recipe is None or not planning_service.is_scheduled_entry(entry):
            continue
        portions = entry.planned_portions or entry.recipe.default_portions
        if not portions:
            continue
        for item in entry.recipe.ingredients:
            ingredient = item.ingredient
            shopping_unit = _shopping_unit_for_item(item.unit, ingredient)
            quantity = item.quantity * Decimal(portions)
            if shopping_unit != item.unit:
                quantity = price_service.convert_quantity(quantity, from_unit=item.unit, to_unit=shopping_unit)
            shopping_date = None
            if assign_shopping_dates:
                shopping_date = entry.shopping_date or _derive_item_shopping_date(entry, camp_year)
            key = (item.ingredient_id, shopping_unit, shopping_date)
            aggregate = aggregates.setdefault(
                key,
                _Aggregate(ingredient_id=item.ingredient_id, unit=shopping_unit, shopping_date=shopping_date),
            )
            aggregate.quantity += quantity
            aggregate.recipe_names.add(entry.recipe.name)
            if entry.meal_date is not None:
                aggregate.needed_dates.add(entry.meal_date)
    return aggregates


def generate_shopping_list(
    session,
    camp_year: CampYear,
    *,
    name: str | None = None,
    price_year: int | None = None,
    assign_shopping_dates: bool = True,
    include_standard_items: bool = True,
) -> ShoppingList:
    """Erzeugt eine neue Einkaufsliste aus dem aktuellen Wochenplan (siehe _aggregate_recipe_items).

    Mit include_standard_items=True (Standard) werden zusaetzlich alle aktiven
    StandardShoppingItem-Vorlagen (Non-Food/Verbrauchsmittel) als eigene Positionen angehaengt -
    bewusst NICHT mit rezeptbasierten Positionen derselben Zutat zusammengefuehrt, damit das
    Signal "linked_recipes_text leer = manuell/Standard" fuer diese Zeilen erhalten bleibt (siehe
    is_manual_item()); im seltenen Fall, dass dieselbe Zutat+Einheit auch rezeptbasiert ohne
    Einkaufstag vorkommt, entstehen dafuer zwei separate, je fuer sich korrekte Zeilen.
    """
    price_year = price_year or camp_year.year
    aggregates = _aggregate_recipe_items(camp_year, assign_shopping_dates=assign_shopping_dates)

    shopping_list = ShoppingList(camp_year=camp_year, name=name or f"Einkaufsliste {camp_year.year}")
    session.add(shopping_list)

    for aggregate in aggregates.values():
        quantity = aggregate.quantity.quantize(Decimal("0.001"))
        estimated_price_per_unit, estimated_total = _estimate_price(session, aggregate.ingredient_id, aggregate.unit, quantity, price_year)
        shopping_list.items.append(
            ShoppingListItem(
                ingredient_id=aggregate.ingredient_id,
                quantity=quantity,
                unit=aggregate.unit,
                estimated_price_per_unit=estimated_price_per_unit,
                estimated_total_price=estimated_total,
                needed_date=min(aggregate.needed_dates) if aggregate.needed_dates else None,
                shopping_date=aggregate.shopping_date,
                status="offen",
                linked_recipes_text=", ".join(sorted(aggregate.recipe_names)),
            )
        )

    if include_standard_items:
        standard_items = session.execute(select(StandardShoppingItem).where(StandardShoppingItem.active.is_(True))).scalars().all()
        for standard_item in standard_items:
            quantity = standard_item.default_quantity.quantize(Decimal("0.001"))
            unit = standard_item.default_unit or (standard_item.ingredient.default_unit if standard_item.ingredient else None)
            estimated_price_per_unit, estimated_total = (None, None)
            if unit:
                estimated_price_per_unit, estimated_total = _estimate_price(session, standard_item.ingredient_id, unit, quantity, price_year)
            shopping_list.items.append(
                ShoppingListItem(
                    ingredient_id=standard_item.ingredient_id,
                    quantity=quantity,
                    unit=unit,
                    estimated_price_per_unit=estimated_price_per_unit,
                    estimated_total_price=estimated_total,
                    status="offen",
                )
            )
    # Ohne den Flush hier loesen frisch angehaengte (noch nicht geflushte) Positionen ihre
    # ".ingredient"-Relationship nicht zuverlaessig auf, wenn direkt im Anschluss (noch in
    # derselben Session) darauf zugegriffen wird.
    session.flush()
    return shopping_list


def append_standard_items_to_shopping_list(session, shopping_list: ShoppingList) -> list[ShoppingListItem]:
    """Fuegt aktive Verbrauchsmittel zu einer bestehenden Einkaufsliste hinzu.

    Idempotent: Existiert fuer dasselbe Verbrauchsmittel bereits eine manuelle/Standard-Zeile
    (kein Rezeptbezug), wird sie nicht erneut angelegt. Rezeptbasierte Zeilen derselben Zutat
    zaehlen bewusst nicht als Duplikat, weil Standard-Verbrauchsmittel separat sichtbar bleiben
    sollen.
    """
    price_year = shopping_list.camp_year.year if shopping_list.camp_year else None
    existing_standard_keys = {
        _ingredient_key(item.ingredient_id, item.unit)
        for item in shopping_list.items
        if is_manual_item(item)
    }
    created: list[ShoppingListItem] = []
    standard_items = session.execute(select(StandardShoppingItem).where(StandardShoppingItem.active.is_(True))).scalars().all()
    for standard_item in standard_items:
        quantity = standard_item.default_quantity.quantize(Decimal("0.001"))
        unit = standard_item.default_unit or (standard_item.ingredient.default_unit if standard_item.ingredient else None)
        key = _ingredient_key(standard_item.ingredient_id, unit)
        if key in existing_standard_keys:
            continue
        estimated_price_per_unit, estimated_total = (None, None)
        if unit and price_year is not None:
            estimated_price_per_unit, estimated_total = _estimate_price(session, standard_item.ingredient_id, unit, quantity, price_year)
        item = ShoppingListItem(
            shopping_list=shopping_list,
            ingredient_id=standard_item.ingredient_id,
            quantity=quantity,
            unit=unit,
            estimated_price_per_unit=estimated_price_per_unit,
            estimated_total_price=estimated_total,
            status="offen",
        )
        session.add(item)
        created.append(item)
        existing_standard_keys.add(key)
    session.flush()
    return created


@dataclass(slots=True)
class ShoppingListUpdateResult:
    created: list[ShoppingListItem]
    updated: list[ShoppingListItem]
    orphaned: list[ShoppingListItem]


def update_shopping_list_from_meal_plan(session, shopping_list: ShoppingList) -> ShoppingListUpdateResult:
    """Gleicht eine bestehende Einkaufsliste mit dem aktuellen Wochenplan ab, statt eine komplett
    neue Liste zu erzeugen - damit nach einer Aenderung am Wochenplan (z. B. andere
    Portionenzahl, neues Rezept) nicht saemtliche bereits geplanten Einkaeufe (Trips/Allocations),
    Sonderwuensche und Verbrauchsmittel-Ergaenzungen verloren gehen.

    Rezeptbasierte Positionen (siehe is_manual_item) werden je Zutat+Einheit+Einkaufstag mit dem
    neu berechneten Bedarf abgeglichen: bestehende Zeilen werden in der Menge aktualisiert, neu
    hinzugekommene Kombinationen werden angelegt. Rezept-Positionen, die im aktuellen Wochenplan
    nicht mehr vorkommen (Rezept/Mahlzeit entfernt), werden NICHT automatisch geloescht - dafuer
    koennten bereits Einkaeufe/Allocations bestehen, ein stilles Loeschen wuerde sie verwaisen
    lassen. Sie werden stattdessen als "orphaned" zurueckgegeben, damit die UI sie anzeigen kann
    und der Nutzer bewusst entscheidet (delete_shopping_list_item lehnt bei bereits zugeteilten
    Positionen ohnehin ab, ist also fuer diesen Fall sicher).

    Sonderwuensche/Verbrauchsmittel (manuelle Positionen) bleiben komplett unangetastet - fuer
    neue Verbrauchsmittel weiterhin separat append_standard_items_to_shopping_list aufrufen.
    """
    camp_year = shopping_list.camp_year
    price_year = camp_year.year if camp_year else None
    assign_shopping_dates = any(
        item.shopping_date is not None for item in shopping_list.items if not is_manual_item(item)
    )
    aggregates = _aggregate_recipe_items(camp_year, assign_shopping_dates=assign_shopping_dates)

    existing_by_key: dict[tuple[int, str, date | None], ShoppingListItem] = {
        (item.ingredient_id, item.unit, item.shopping_date): item
        for item in shopping_list.items
        if not is_manual_item(item)
    }

    created: list[ShoppingListItem] = []
    updated: list[ShoppingListItem] = []
    seen_keys: set[tuple[int, str, date | None]] = set()

    for key, aggregate in aggregates.items():
        seen_keys.add(key)
        quantity = aggregate.quantity.quantize(Decimal("0.001"))
        needed_date = min(aggregate.needed_dates) if aggregate.needed_dates else None
        recipes_text = ", ".join(sorted(aggregate.recipe_names))
        existing = existing_by_key.get(key)
        if existing is not None:
            if existing.quantity != quantity or existing.needed_date != needed_date or existing.linked_recipes_text != recipes_text:
                existing.quantity = quantity
                existing.needed_date = needed_date
                existing.linked_recipes_text = recipes_text
                if price_year is not None:
                    existing.estimated_price_per_unit, existing.estimated_total_price = _estimate_price(
                        session, aggregate.ingredient_id, aggregate.unit, quantity, price_year
                    )
                updated.append(existing)
        else:
            estimated_price_per_unit, estimated_total = (None, None)
            if price_year is not None:
                estimated_price_per_unit, estimated_total = _estimate_price(
                    session, aggregate.ingredient_id, aggregate.unit, quantity, price_year
                )
            item = ShoppingListItem(
                shopping_list=shopping_list,
                ingredient_id=aggregate.ingredient_id,
                quantity=quantity,
                unit=aggregate.unit,
                estimated_price_per_unit=estimated_price_per_unit,
                estimated_total_price=estimated_total,
                needed_date=needed_date,
                shopping_date=aggregate.shopping_date,
                status="offen",
                linked_recipes_text=recipes_text,
            )
            session.add(item)
            created.append(item)

    orphaned = [item for key, item in existing_by_key.items() if key not in seen_keys]

    session.flush()
    return ShoppingListUpdateResult(created=created, updated=updated, orphaned=orphaned)


def _shopping_unit_for_item(item_unit: str, ingredient: Ingredient | None) -> str:
    default_unit = ingredient.default_unit if ingredient else None
    normalized_item_unit = price_service.normalize_unit(item_unit)
    normalized_default_unit = price_service.normalize_unit(default_unit)
    if normalized_item_unit and normalized_default_unit and price_service.can_convert_units(normalized_item_unit, normalized_default_unit):
        return normalized_default_unit
    return normalized_item_unit or item_unit


def is_manual_item(item: ShoppingListItem) -> bool:
    """Eine Position ohne Rezeptbezug - entweder ueber "Position hinzufuegen" spontan angelegt
    oder aus einer StandardShoppingItem-Vorlage uebernommen. linked_recipes_text wird
    ausschliesslich von generate_shopping_list() beim Verarbeiten von Rezepten gesetzt und ist
    dort garantiert nicht-leer - daher reicht die Abwesenheit als zuverlaessiges Signal, ohne
    dass eine eigene Spalte gepflegt werden muss."""
    return not item.linked_recipes_text


def add_manual_shopping_item(
    session,
    shopping_list: ShoppingList,
    *,
    ingredient: Ingredient,
    quantity: Decimal,
    unit: str | None,
    requested_by: str | None = None,
    notes: str | None = None,
    price_year: int | None = None,
) -> ShoppingListItem:
    """Haengt eine spontane Position (Sonderwunsch) an eine bereits bestehende Einkaufsliste an -
    kein Rezeptbezug, taucht ganz normal in Wochenliste/Gesamtliste/"Einkauf planen" auf."""
    if quantity <= 0:
        raise ValueError("Menge muss größer als 0 sein.")
    quantity = quantity.quantize(Decimal("0.001"))
    resolved_year = price_year or shopping_list.camp_year.year
    estimated_price_per_unit, estimated_total = (None, None)
    if unit:
        estimated_price_per_unit, estimated_total = _estimate_price(session, ingredient.id, unit, quantity, resolved_year)
    item = ShoppingListItem(
        shopping_list=shopping_list,
        ingredient_id=ingredient.id,
        quantity=quantity,
        unit=unit,
        estimated_price_per_unit=estimated_price_per_unit,
        estimated_total_price=estimated_total,
        status="offen",
        requested_by=(requested_by or "").strip() or None,
        notes=(notes or "").strip() or None,
    )
    session.add(item)
    session.flush()
    return item


def delete_shopping_list_item(session, item: ShoppingListItem) -> None:
    """Entfernt eine einzelne Position (Sonderwunsch/Verbrauchsmittel) wieder aus der Liste.

    Bewusst nur fuer manuelle Positionen (siehe is_manual_item) - rezeptbasierte Zeilen sind das
    Ergebnis der Wochenplan-Aggregation und sollen ueber den Wochenplan bzw. "Einkaufsliste
    aktualisieren" gepflegt werden, nicht per Einzel-Loeschung, sonst kaeme beim naechsten
    Aktualisieren/Generieren dieselbe Zeile wieder. Ist die Position bereits einem Einkauf
    zugeteilt, wird die Loeschung abgelehnt statt die Allocation zu verwaisen - erst im
    zugehoerigen Einkauf entfernen/neu zuteilen, dann hier loeschen."""
    if not is_manual_item(item):
        raise ValueError("Nur Sonderwünsche/Verbrauchsmittel können einzeln gelöscht werden, keine Rezept-Positionen.")
    has_allocation = session.execute(
        select(ShoppingListItemAllocation.id).where(ShoppingListItemAllocation.shopping_list_item_id == item.id)
    ).first()
    if has_allocation:
        raise ValueError("Position ist bereits einem Einkauf zugeteilt - bitte zuerst dort entfernen.")
    session.delete(item)
    session.flush()


def previous_year_quantity(session, camp_year: CampYear, ingredient_id: int, unit: str | None) -> Decimal | None:
    """Summe der Menge dieser Zutat+Einheit im letzten Camp-Jahr VOR camp_year.year, das eine
    Einkaufsliste hat - rein informativ, um beim Pflegen von Standard-/manuellen Positionen den
    Vorjahresbedarf als Anhaltspunkt zu zeigen (kein Auto-Ausfuellen)."""
    key = _ingredient_key(ingredient_id, unit)
    previous_years = session.execute(
        select(CampYear)
        .join(ShoppingList, ShoppingList.camp_year_id == CampYear.id)
        .where(CampYear.year < camp_year.year)
        .order_by(CampYear.year.desc())
    ).scalars().unique().all()
    if not previous_years:
        return None
    latest_previous = previous_years[0]
    total = Decimal("0")
    found = False
    for shopping_list in latest_previous.shopping_lists:
        for item in shopping_list.items:
            if (item.ingredient_id, item.unit or "") == key:
                total += item.quantity
                found = True
    return total if found else None


def list_standard_items(session, *, active_only: bool = False) -> list[StandardShoppingItem]:
    stmt = select(StandardShoppingItem)
    if active_only:
        stmt = stmt.where(StandardShoppingItem.active.is_(True))
    items = session.execute(stmt).scalars().all()
    return sorted(items, key=lambda item: (item.ingredient.name if item.ingredient else "").lower())


def create_standard_item(
    session,
    *,
    ingredient: Ingredient,
    default_quantity: Decimal,
    default_unit: str | None,
    typical_stock_note: str | None = None,
    notes: str | None = None,
) -> StandardShoppingItem:
    if default_quantity <= 0:
        raise ValueError("Menge muss größer als 0 sein.")
    item = StandardShoppingItem(
        ingredient=ingredient,
        default_quantity=default_quantity.quantize(Decimal("0.001")),
        default_unit=default_unit,
        typical_stock_note=(typical_stock_note or "").strip() or None,
        notes=(notes or "").strip() or None,
    )
    session.add(item)
    session.flush()
    return item


def update_standard_item(item: StandardShoppingItem, **fields: object) -> StandardShoppingItem:
    for key, value in fields.items():
        if not hasattr(item, key):
            raise AttributeError(f"Unbekanntes Feld: {key}")
        setattr(item, key, value)
    return item


def delete_standard_item(session, item: StandardShoppingItem) -> None:
    session.delete(item)
    session.flush()


def group_by_shopping_day(shopping_list: ShoppingList) -> dict[date | None, list[ShoppingListItem]]:
    groups: dict[date | None, list[ShoppingListItem]] = defaultdict(list)
    for item in shopping_list.items:
        groups[item.shopping_date].append(item)
    return dict(groups)


def grouped_by_day_ordered(shopping_list: ShoppingList) -> list[tuple[date | None, list[ShoppingListItem]]]:
    """Tage aufsteigend sortiert, Positionen ohne Einkaufstag zuletzt."""
    groups = group_by_shopping_day(shopping_list)
    return sorted(groups.items(), key=lambda pair: (pair[0] is None, pair[0]))


@dataclass(slots=True)
class AggregatedShoppingItem:
    ingredient_name: str
    quantity: Decimal
    unit: str
    estimated_total_price: Decimal | None
    has_missing_price: bool


def aggregated_items_sorted(shopping_list: ShoppingList) -> list[AggregatedShoppingItem]:
    """Fasst Positionen derselben Zutat+Einheit zu einer Zeile mit Gesamtmenge zusammen (z. B.
    wenn dieselbe Zutat an mehreren Einkaufstagen gebraucht wird) und sortiert alphabetisch nach
    Zutatname - fuer die ungruppierte Ansicht/den PDF-Export ohne Tag/Händler-Gliederung, wo
    dieselbe Zutat sonst mehrfach als unsortierte Teilmenge auftaucht statt als eine Gesamtmenge."""
    groups: dict[tuple[object, str], list[ShoppingListItem]] = defaultdict(list)
    for item in shopping_list.items:
        group_key = item.ingredient_id if item.ingredient_id is not None else f"_item_{item.id}"
        groups[(group_key, item.unit or "")].append(item)

    aggregated: list[AggregatedShoppingItem] = []
    for items in groups.values():
        name = items[0].ingredient.name if items[0].ingredient else ""
        total_quantity = sum((item.quantity for item in items), Decimal("0"))
        total_price = None
        if all(item.estimated_total_price is not None for item in items):
            total_price = sum((item.estimated_total_price for item in items), Decimal("0"))
        aggregated.append(
            AggregatedShoppingItem(
                ingredient_name=name,
                quantity=total_quantity,
                unit=items[0].unit or "",
                estimated_total_price=total_price,
                has_missing_price=any(item.estimated_price_per_unit is None for item in items),
            )
        )
    aggregated.sort(key=lambda row: row.ingredient_name.lower())
    return aggregated


GERMAN_WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def format_shopping_day_label(shopping_date: date | None) -> str:
    if shopping_date is None:
        return "Ohne Einkaufstag"
    return f"{GERMAN_WEEKDAYS[shopping_date.weekday()]}, {shopping_date.strftime('%d.%m.%Y')}"


def format_date_de(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def format_quantity_de(value: Decimal | None) -> str:
    """Menge ohne unnoetige Nachkommastellen (z. B. "20" statt "20.000", "2.5" statt "2.500")."""
    if value is None:
        return ""
    text = f"{value:.3f}".rstrip("0").rstrip(".")
    return text or "0"


def list_known_stores(session) -> list[str]:
    """Alle bisher an Einkaufspositionen vergebenen Händlernamen, dedupliziert und alphabetisch -
    fuer eine Autovervollstaendigungs-Vorschlagsliste (siehe shopping_view.py), damit z. B.
    "Edeka"/"EDEKA"/"Edeka Regensburg" nicht als getrennte Gruppen in der Nach-Händler-Ansicht
    auseinanderlaufen."""
    rows = session.execute(select(ShoppingListItem.store).where(ShoppingListItem.store.isnot(None))).scalars().all()
    unique_stores = {store.strip() for store in rows if store and store.strip()}
    return sorted(unique_stores, key=str.lower)


ALLOWED_ITEM_STATUSES = ("offen", "bestellt", "gekauft", "erledigt", "pruefen")


# --- Einkauf planen: Trips & Allocations ------------------------------------------------
# Eine Gesamtposition (ShoppingListItem) wird ueber den "Einkauf planen"-Assistenten
# (Desktop & Mobile) einem oder mehreren ShoppingTrips zugeteilt. Jeder Trip hat einen
# Haendler und Teilnehmer; die dabei ausgewaehlten Teilmengen (Allocations) werden zufaellig
# gleichmaessig auf die Teilnehmer verteilt. ShoppingListItem.store/.status werden dafuer
# nicht mehr beschrieben (siehe migrate_legacy_store_status fuer die Altdaten-Uebernahme).

UNASSIGNED_PERSON_LABEL = "Ohne Zuordnung"


def _ingredient_key(ingredient_id: int | None, unit: str | None) -> tuple[int | None, str]:
    return (ingredient_id, unit or "")


def _representative_item(shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None) -> ShoppingListItem:
    key = _ingredient_key(ingredient_id, unit)
    for item in shopping_list.items:
        if _ingredient_key(item.ingredient_id, item.unit) == key:
            return item
    raise ValueError("Keine passende Einkaufslistenposition fuer diese Zutat gefunden.")


def _ingredient_totals(shopping_list: ShoppingList) -> dict[tuple[int | None, str], Decimal]:
    """Gesamtbedarf je Zutat+Einheit ueber alle ShoppingListItem-Zeilen (Einkaufstage) hinweg."""
    totals: dict[tuple[int | None, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for item in shopping_list.items:
        totals[_ingredient_key(item.ingredient_id, item.unit)] += item.quantity
    return totals


def _allocated_totals(shopping_list: ShoppingList) -> dict[tuple[int | None, str], Decimal]:
    """Bereits auf Einkaeufe (Trips) verteilte Menge je Zutat+Einheit."""
    totals: dict[tuple[int | None, str], Decimal] = defaultdict(lambda: Decimal("0"))
    for allocation in shopping_list.allocations:
        totals[_ingredient_key(allocation.ingredient_id, allocation.unit)] += allocation.quantity
    return totals


def remaining_quantity_for_ingredient(shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None) -> Decimal:
    """Menge einer Zutat (Gesamtbedarf ueber alle Einkaufstage), die noch keinem Einkauf
    zugeteilt ist."""
    key = _ingredient_key(ingredient_id, unit)
    total = _ingredient_totals(shopping_list).get(key, Decimal("0"))
    allocated = _allocated_totals(shopping_list).get(key, Decimal("0"))
    return total - allocated


def purchased_quantity_for_ingredient(shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None) -> Decimal:
    key = _ingredient_key(ingredient_id, unit)
    return sum(
        (
            allocation.purchased_quantity or Decimal("0")
            for allocation in shopping_list.allocations
            if _ingredient_key(allocation.ingredient_id, allocation.unit) == key and allocation.status == "gekauft"
        ),
        Decimal("0"),
    )


def purchase_history_summary(shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None) -> str:
    key = _ingredient_key(ingredient_id, unit)
    parts = []
    for allocation in sorted(
        shopping_list.allocations,
        key=lambda a: (a.purchased_at is None, a.purchased_at or a.created_at, a.trip.store.lower()),
    ):
        if _ingredient_key(allocation.ingredient_id, allocation.unit) != key or allocation.status != "gekauft":
            continue
        quantity = allocation.purchased_quantity if allocation.purchased_quantity is not None else allocation.quantity
        date_text = format_date_de(allocation.purchased_at.date()) if allocation.purchased_at else "ohne Datum"
        parts.append(f"{format_quantity_de(quantity)} {unit or ''} am {date_text} bei {allocation.trip.store}".strip())
    return ", ".join(parts)


def need_purchase_remaining_summary(
    shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None
) -> tuple[Decimal, Decimal, Decimal, str]:
    key = _ingredient_key(ingredient_id, unit)
    needed = _ingredient_totals(shopping_list).get(key, Decimal("0"))
    purchased = purchased_quantity_for_ingredient(shopping_list, ingredient_id, unit)
    remaining = needed - purchased
    if remaining < 0:
        remaining = Decimal("0")
    return needed, purchased, remaining, purchase_history_summary(shopping_list, ingredient_id, unit)


@dataclass(slots=True)
class PlannableIngredientGroup:
    """Eine Zutat mit ihrer noch offenen Gesamtmenge (ueber alle Einkaufstage zusammengefasst) -
    Datenquelle fuer den "Einkauf planen"-Assistenten. Eine hier ausgewaehlte Menge wird zu
    GENAU EINEM Listeneintrag (einer Allocation), unabhaengig davon, auf wie viele
    ShoppingListItem-Zeilen der Bedarf im Wochenplan urspruenglich verteilt war."""

    ingredient_id: int | None
    ingredient_name: str
    unit: str
    remaining_quantity: Decimal


def items_available_for_planning(shopping_list: ShoppingList) -> list[PlannableIngredientGroup]:
    """Zutaten mit noch nicht zugeteilter Restmenge, alphabetisch sortiert."""
    totals = _ingredient_totals(shopping_list)
    allocated = _allocated_totals(shopping_list)
    names: dict[tuple[int | None, str], str] = {}
    for item in shopping_list.items:
        names[_ingredient_key(item.ingredient_id, item.unit)] = item.ingredient.name if item.ingredient else ""

    result = []
    for key, total in totals.items():
        remaining = total - allocated.get(key, Decimal("0"))
        if remaining <= 0:
            continue
        ingredient_id, unit = key
        result.append(
            PlannableIngredientGroup(
                ingredient_id=ingredient_id, ingredient_name=names.get(key, ""), unit=unit, remaining_quantity=remaining
            )
        )
    result.sort(key=lambda group: group.ingredient_name.lower())
    return result


def _parse_participants(participants_text: str | None) -> list[str]:
    if not participants_text:
        return []
    return [name.strip() for name in participants_text.split(",") if name.strip()]


def _distribute_randomly(allocations: list[ShoppingListItemAllocation], participants: list[str]) -> None:
    """Verteilt zufaellig gleichmaessig auf die Teilnehmer - jede Allocation ist bereits ein
    einzelner Listeneintrag (eine Zutat mit Gesamtmenge), geht also immer komplett an eine
    Person."""
    if not participants:
        for allocation in allocations:
            allocation.assigned_to = None
        return
    shuffled = list(allocations)
    random.shuffle(shuffled)
    for index, allocation in enumerate(shuffled):
        allocation.assigned_to = participants[index % len(participants)]


def create_shopping_trip(
    session,
    shopping_list: ShoppingList,
    *,
    store: str,
    participants: list[str],
    selections: list[tuple[int | None, str, Decimal]],
) -> ShoppingTrip:
    """Legt einen Einkauf (Trip) an: waehlt Gesamtmengen noch offener Zutaten fuer einen
    Haendler aus und verteilt sie zufaellig gleichmaessig auf die Teilnehmer.

    `selections` sind (ingredient_id, unit, gewuenschte Menge)-Tripel, wie sie
    items_available_for_planning liefert - jede Auswahl wird zu genau einer Allocation
    (einem Listeneintrag), es wird nichts auf mehrere Zeilen aufgesplittet."""
    store = store.strip()
    if not store:
        raise ValueError("Händler darf nicht leer sein.")
    if not selections:
        raise ValueError("Mindestens eine Position auswählen.")

    names: dict[tuple[int | None, str], str] = {}
    for item in shopping_list.items:
        names[_ingredient_key(item.ingredient_id, item.unit)] = item.ingredient.name if item.ingredient else ""

    for ingredient_id, unit, quantity in selections:
        key = _ingredient_key(ingredient_id, unit)
        label = names.get(key) or str(ingredient_id)
        if quantity <= 0:
            raise ValueError(f"Menge für '{label}' muss größer als 0 sein.")
        if quantity > remaining_quantity_for_ingredient(shopping_list, ingredient_id, unit):
            raise ValueError(f"Menge für '{label}' übersteigt die noch offene Restmenge.")

    trip = ShoppingTrip(shopping_list=shopping_list, store=store, participants_text=", ".join(participants) or None)
    session.add(trip)
    for ingredient_id, unit, quantity in selections:
        item = _representative_item(shopping_list, ingredient_id, unit)
        trip.allocations.append(
            ShoppingListItemAllocation(
                shopping_list=shopping_list,
                shopping_list_item=item,
                ingredient_id=ingredient_id,
                unit=unit,
                quantity=quantity,
                status="offen",
            )
        )

    _distribute_randomly(trip.allocations, participants)
    session.flush()
    return trip


def add_allocations_to_trip(
    session,
    trip: ShoppingTrip,
    selections: list[tuple[int | None, str, Decimal]],
) -> list[ShoppingListItemAllocation]:
    """Haengt weitere offene Positionen an einen bestehenden Einkauf an.

    Wird im Desktop-Dialog "Einkauf bearbeiten" genutzt, wenn beim Bearbeiten noch nicht
    verplante Restmengen in denselben Einkauf aufgenommen werden sollen.
    """
    if not selections:
        return []

    shopping_list = trip.shopping_list
    names: dict[tuple[int | None, str], str] = {}
    for item in shopping_list.items:
        names[_ingredient_key(item.ingredient_id, item.unit)] = item.ingredient.name if item.ingredient else ""

    for ingredient_id, unit, quantity in selections:
        key = _ingredient_key(ingredient_id, unit)
        label = names.get(key) or str(ingredient_id)
        if quantity <= 0:
            raise ValueError(f"Menge fuer '{label}' muss groesser als 0 sein.")
        if quantity > remaining_quantity_for_ingredient(shopping_list, ingredient_id, unit):
            raise ValueError(f"Menge fuer '{label}' uebersteigt die noch offene Restmenge.")

    participants = _parse_participants(trip.participants_text)
    created: list[ShoppingListItemAllocation] = []
    for ingredient_id, unit, quantity in selections:
        item = _representative_item(shopping_list, ingredient_id, unit)
        allocation = ShoppingListItemAllocation(
            shopping_list=shopping_list,
            shopping_list_item=item,
            ingredient_id=ingredient_id,
            unit=unit,
            quantity=quantity,
            status="offen",
        )
        trip.allocations.append(allocation)
        created.append(allocation)

    _distribute_randomly(created, participants)
    session.flush()
    return created


def reshuffle_trip_assignments(trip: ShoppingTrip, participants: list[str] | None = None) -> None:
    """Verteilt die noch offenen (nicht abgehakten) Allocations eines Trips neu zufaellig -
    deckt "jemand faellt aus/kommt dazu" ab, ohne den Trip neu anzulegen."""
    names = participants if participants is not None else _parse_participants(trip.participants_text)
    if participants is not None:
        trip.participants_text = ", ".join(names) or None
    open_allocations = [allocation for allocation in trip.allocations if allocation.status != "gekauft"]
    _distribute_randomly(open_allocations, names)


def set_allocation_assigned_to(allocation: ShoppingListItemAllocation, name: str | None) -> ShoppingListItemAllocation:
    allocation.assigned_to = (name or "").strip() or None
    return allocation


def set_allocation_status(allocation: ShoppingListItemAllocation, status: str) -> ShoppingListItemAllocation:
    if status not in ALLOWED_ITEM_STATUSES:
        raise ValueError(f"Ungültiger Status '{status}'. Erlaubt: {', '.join(ALLOWED_ITEM_STATUSES)}")
    allocation.status = status
    return allocation


def set_allocation_quantity(
    shopping_list: ShoppingList, allocation: ShoppingListItemAllocation, quantity: Decimal
) -> ShoppingListItemAllocation:
    """Aendert die Menge einer bestehenden Allocation nachtraeglich - z. B. wenn beim Planen
    verschaetzt wurde. Gedeckelt durch die Menge, die dieser Zutat insgesamt noch zur Verfuegung
    steht (diese Allocation eingerechnet, sonst wuerde sie sich selbst im Weg stehen)."""
    if quantity <= 0:
        raise ValueError("Menge muss größer als 0 sein.")
    available = remaining_quantity_for_ingredient(shopping_list, allocation.ingredient_id, allocation.unit) + allocation.quantity
    if quantity > available:
        label = allocation.ingredient.name if allocation.ingredient else str(allocation.ingredient_id)
        raise ValueError(
            f"Menge für '{label}' übersteigt die verfügbare Menge ({format_quantity_de(available)} {allocation.unit or ''})."
        )
    allocation.quantity = quantity
    return allocation


def mark_allocation_purchased(
    allocation: ShoppingListItemAllocation, purchased_quantity: Decimal | None = None
) -> ShoppingListItemAllocation:
    allocation.status = "gekauft"
    allocation.purchased_quantity = purchased_quantity if purchased_quantity is not None else allocation.quantity
    allocation.purchased_at = datetime.now(timezone.utc)
    return allocation


def mark_allocation_open(allocation: ShoppingListItemAllocation) -> ShoppingListItemAllocation:
    allocation.status = "offen"
    allocation.purchased_quantity = None
    allocation.purchased_at = None
    return allocation


def delete_allocation(session, allocation: ShoppingListItemAllocation) -> None:
    session.delete(allocation)
    session.flush()


def delete_shopping_trip(session, trip: ShoppingTrip) -> None:
    session.delete(trip)
    session.flush()


def grouped_by_store_ordered_allocations(shopping_list: ShoppingList) -> list[tuple[str, list[ShoppingListItemAllocation]]]:
    """Allocations aller Trips einer Liste, gruppiert nach Händler (alphabetisch)."""
    groups: dict[str, list[ShoppingListItemAllocation]] = defaultdict(list)
    for allocation in shopping_list.allocations:
        groups[allocation.trip.store].append(allocation)
    return sorted(groups.items(), key=lambda pair: pair[0].lower())


def grouped_by_person_ordered(shopping_list: ShoppingList) -> list[tuple[str | None, list[ShoppingListItemAllocation]]]:
    """Allocations aller Trips einer Liste, gruppiert nach zugewiesener Person (unzugeordnet zuletzt)."""
    groups: dict[str | None, list[ShoppingListItemAllocation]] = defaultdict(list)
    for allocation in shopping_list.allocations:
        groups[allocation.assigned_to].append(allocation)
    return sorted(groups.items(), key=lambda pair: (pair[0] is None, (pair[0] or "").lower()))


def migrate_legacy_store_status(session, shopping_list: ShoppingList) -> None:
    """Einmalige, idempotente Übernahme alter item.store/item.status-Werte (aus der Zeit vor
    Trips/Allocations) in je einen "Altbestand"-Trip pro Händlerwert. Zutaten, die bereits eine
    Allocation haben, werden übersprungen (schon migriert oder schon frisch über "Einkauf
    planen" angelegt). Legacy-Zeilen werden nach (Zutat, Einheit, Händler) gruppiert und ihre
    Mengen summiert - Zeilen ohne Händler (store=None) zählen dabei bewusst nicht mit."""
    already_allocated = {_ingredient_key(a.ingredient_id, a.unit) for a in shopping_list.allocations}
    trips_by_store: dict[str, ShoppingTrip] = {trip.store: trip for trip in shopping_list.trips}

    groups: dict[tuple[int | None, str, str], list[ShoppingListItem]] = defaultdict(list)
    for item in shopping_list.items:
        key = _ingredient_key(item.ingredient_id, item.unit)
        if key in already_allocated or not item.store:
            continue
        groups[(item.ingredient_id, item.unit or "", item.store)].append(item)

    for (ingredient_id, unit, store), group_items in groups.items():
        trip = trips_by_store.get(store)
        if trip is None:
            trip = ShoppingTrip(shopping_list=shopping_list, store=store)
            session.add(trip)
            trips_by_store[store] = trip
        total_quantity = sum((item.quantity for item in group_items), Decimal("0"))
        status = next((item.status for item in group_items if item.status), None) or "offen"
        trip.allocations.append(
            ShoppingListItemAllocation(
                shopping_list=shopping_list,
                shopping_list_item=group_items[0],
                ingredient_id=ingredient_id,
                unit=unit,
                quantity=total_quantity,
                status=status,
            )
        )
    session.flush()


def ingredient_price_per_unit(shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None) -> Decimal | None:
    """Preis je Einheit einer Zutat, hergeleitet aus der ersten Wochenplan-Position mit
    hinterlegtem Preis - fuer die Anzeige auf Allocation-Zeilen (Nach Händler/Nutzer), die
    selbst keinen eigenen Preis fuehren."""
    for item in shopping_list.items:
        if _ingredient_key(item.ingredient_id, item.unit) == _ingredient_key(ingredient_id, unit) and item.estimated_price_per_unit is not None:
            return item.estimated_price_per_unit
    return None


def ingredient_linked_recipes(shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None) -> str:
    """Rezepte, die diese Zutat brauchen - fuer die Anzeige auf Allocation-Zeilen."""
    names: set[str] = set()
    for item in shopping_list.items:
        if _ingredient_key(item.ingredient_id, item.unit) == _ingredient_key(ingredient_id, unit) and item.linked_recipes_text:
            names.update(name.strip() for name in item.linked_recipes_text.split(",") if name.strip())
    return ", ".join(sorted(names))


def ingredient_requested_by(shopping_list: ShoppingList, ingredient_id: int | None, unit: str | None) -> str | None:
    """Wer eine manuelle Position (Sonderwunsch) gewuenscht hat - fuer die Anzeige auf
    Allocation-Zeilen. None, falls keine der zugrundeliegenden Positionen manuell ist."""
    key = _ingredient_key(ingredient_id, unit)
    names = {
        item.requested_by
        for item in shopping_list.items
        if _ingredient_key(item.ingredient_id, item.unit) == key and item.requested_by
    }
    return ", ".join(sorted(names)) if names else None


def allocation_store_summary(item: ShoppingListItem) -> str:
    """Kompakte Anzeige der geplanten Händler+Mengen einer Zutat - für den flachen
    CSV/Excel-Export, der weiterhin eine einzelne Händler-Spalte pro (Tages-)Zeile zeigt.
    Zeigt dieselbe Zutat-Zuteilung auf allen Tages-Zeilen dieser Zutat an, da Allocations
    jetzt zutatenbezogen statt tagesbezogen sind."""
    key = _ingredient_key(item.ingredient_id, item.unit)
    matching = [a for a in item.shopping_list.allocations if _ingredient_key(a.ingredient_id, a.unit) == key]
    if not matching:
        return ""
    parts = [f"{allocation.trip.store} ({format_quantity_de(allocation.quantity)} {item.unit or ''})".strip() for allocation in matching]
    return ", ".join(parts)


def allocation_status_summary(item: ShoppingListItem) -> str:
    """Kompakter Gesamtstatus einer Zutat über alle Allocations hinweg - für den
    CSV/Excel-Export."""
    key = _ingredient_key(item.ingredient_id, item.unit)
    matching = [a for a in item.shopping_list.allocations if _ingredient_key(a.ingredient_id, a.unit) == key]
    if not matching:
        return "offen"
    if remaining_quantity_for_ingredient(item.shopping_list, item.ingredient_id, item.unit) > 0:
        return "teilweise geplant"
    if all(allocation.status == "gekauft" for allocation in matching):
        return "gekauft"
    return "offen"


def total_estimated_cost(shopping_list: ShoppingList) -> Decimal:
    return total_items_estimated_cost(shopping_list.items)


def total_items_estimated_cost(items) -> Decimal:
    return sum((item.estimated_total_price or Decimal("0") for item in items), Decimal("0")).quantize(Decimal("0.01"))


def delete_shopping_list(session, shopping_list: ShoppingList) -> None:
    session.delete(shopping_list)
    session.flush()
