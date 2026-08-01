from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.models import CampYear, Ingredient, ShoppingList, ShoppingListItem
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


def generate_shopping_list(
    session,
    camp_year: CampYear,
    *,
    name: str | None = None,
    price_year: int | None = None,
    assign_shopping_dates: bool = True,
) -> ShoppingList:
    """Aggregiert alle geplanten (nicht abgesagten) Mahlzeiten eines Camp-Jahrs zu einer Einkaufsliste.

    Der Einkaufstag je Position wird automatisch hergeleitet (siehe _derive_item_shopping_date),
    sofern am Mahlzeit-Slot im Wochenplan kein Einkaufstag manuell gesetzt wurde. Mit
    assign_shopping_dates=False entsteht stattdessen eine Gesamtliste ohne Einkaufstage
    (das Bedarfsdatum - wann die Zutat fuer eine Mahlzeit gebraucht wird - wird trotzdem gefuellt).
    """
    price_year = price_year or camp_year.year
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

    shopping_list = ShoppingList(camp_year=camp_year, name=name or f"Einkaufsliste {camp_year.year}")
    session.add(shopping_list)

    for aggregate in aggregates.values():
        best_price = price_service.find_best_price(
            session,
            aggregate.ingredient_id,
            year=price_year,
            fallback_latest=False,
        )
        quantity = aggregate.quantity.quantize(Decimal("0.001"))
        estimated_price_per_unit = None
        estimated_total = None
        if best_price and price_service.can_convert_units(best_price.unit, aggregate.unit):
            estimated_price_per_unit = price_service.convert_price_per_unit(
                best_price.price_per_unit,
                from_unit=best_price.unit,
                to_unit=aggregate.unit,
            ).quantize(Decimal("0.0001"))
            estimated_total = (quantity * estimated_price_per_unit).quantize(Decimal("0.01"))

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
    return shopping_list


def _shopping_unit_for_item(item_unit: str, ingredient: Ingredient | None) -> str:
    default_unit = ingredient.default_unit if ingredient else None
    normalized_item_unit = price_service.normalize_unit(item_unit)
    normalized_default_unit = price_service.normalize_unit(default_unit)
    if normalized_item_unit and normalized_default_unit and price_service.can_convert_units(normalized_item_unit, normalized_default_unit):
        return normalized_default_unit
    return normalized_item_unit or item_unit


def group_by_shopping_day(shopping_list: ShoppingList) -> dict[date | None, list[ShoppingListItem]]:
    groups: dict[date | None, list[ShoppingListItem]] = defaultdict(list)
    for item in shopping_list.items:
        groups[item.shopping_date].append(item)
    return dict(groups)


def group_by_store(shopping_list: ShoppingList) -> dict[str | None, list[ShoppingListItem]]:
    groups: dict[str | None, list[ShoppingListItem]] = defaultdict(list)
    for item in shopping_list.items:
        groups[item.store].append(item)
    return dict(groups)


def filter_by_store(shopping_list: ShoppingList, store: str) -> list[ShoppingListItem]:
    return [item for item in shopping_list.items if item.store == store]


def grouped_by_day_ordered(shopping_list: ShoppingList) -> list[tuple[date | None, list[ShoppingListItem]]]:
    """Tage aufsteigend sortiert, Positionen ohne Einkaufstag zuletzt."""
    groups = group_by_shopping_day(shopping_list)
    return sorted(groups.items(), key=lambda pair: (pair[0] is None, pair[0]))


def grouped_by_store_ordered(shopping_list: ShoppingList) -> list[tuple[str | None, list[ShoppingListItem]]]:
    """Händler alphabetisch sortiert, Positionen ohne Händler zuletzt."""
    groups = group_by_store(shopping_list)
    return sorted(groups.items(), key=lambda pair: (pair[0] is None, (pair[0] or "").lower()))


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


UNASSIGNED_STORE_LABEL = "Ohne Händler"
GERMAN_WEEKDAYS = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def format_shopping_day_label(shopping_date: date | None) -> str:
    if shopping_date is None:
        return "Ohne Einkaufstag"
    return f"{GERMAN_WEEKDAYS[shopping_date.weekday()]}, {shopping_date.strftime('%d.%m.%Y')}"


def format_date_de(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def set_item_store(item: ShoppingListItem, store: str | None) -> ShoppingListItem:
    item.store = (store or "").strip() or None
    return item


def list_known_stores(session) -> list[str]:
    """Alle bisher an Einkaufspositionen vergebenen Händlernamen, dedupliziert und alphabetisch -
    fuer eine Autovervollstaendigungs-Vorschlagsliste (siehe shopping_view.py), damit z. B.
    "Edeka"/"EDEKA"/"Edeka Regensburg" nicht als getrennte Gruppen in der Nach-Händler-Ansicht
    auseinanderlaufen."""
    rows = session.execute(select(ShoppingListItem.store).where(ShoppingListItem.store.isnot(None))).scalars().all()
    unique_stores = {store.strip() for store in rows if store and store.strip()}
    return sorted(unique_stores, key=str.lower)


ALLOWED_ITEM_STATUSES = ("offen", "bestellt", "gekauft", "erledigt", "pruefen")


def set_item_status(item: ShoppingListItem, status: str) -> ShoppingListItem:
    if status not in ALLOWED_ITEM_STATUSES:
        raise ValueError(f"Ungültiger Status '{status}'. Erlaubt: {', '.join(ALLOWED_ITEM_STATUSES)}")
    item.status = status
    return item


def total_estimated_cost(shopping_list: ShoppingList) -> Decimal:
    return total_items_estimated_cost(shopping_list.items)


def total_items_estimated_cost(items) -> Decimal:
    return sum((item.estimated_total_price or Decimal("0") for item in items), Decimal("0")).quantize(Decimal("0.01"))


def delete_shopping_list(session, shopping_list: ShoppingList) -> None:
    session.delete(shopping_list)
    session.flush()
