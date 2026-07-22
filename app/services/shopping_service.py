from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from app.models import CampYear, Ingredient, ShoppingList, ShoppingListItem
from app.services import planning_service, price_service


@dataclass(slots=True)
class _Aggregate:
    ingredient_id: int
    unit: str
    quantity: Decimal = Decimal("0")
    recipe_names: set[str] = field(default_factory=set)
    needed_dates: set[date] = field(default_factory=set)
    shopping_dates: set[date] = field(default_factory=set)


# Lagerarten, die sich bevorraten lassen: einmaliger Einkauf zu Lagerbeginn statt taeglich
# frisch. Freitext-Feld (Ingredient.storage_type), daher Schluesselwort-Abgleich statt Enum.
SHELF_STABLE_KEYWORDS = ("trocken", "tiefkuehl", "tiefkühl", "tk", "konserve", "getraenke", "getränke", "vorrat")


def _is_shelf_stable(ingredient: Ingredient | None) -> bool:
    storage_type = (ingredient.storage_type or "").lower() if ingredient else ""
    return any(keyword in storage_type for keyword in SHELF_STABLE_KEYWORDS)


def _derive_item_shopping_date(entry, ingredient: Ingredient | None, camp_year: CampYear) -> date | None:
    """Automatischer Einkaufstag, wenn am Mahlzeit-Slot keiner manuell gesetzt wurde.

    Frische Zutaten: ein Tag vor der Mahlzeit (moeglichst kurze Lagerzeit).
    Lagerfaehige Zutaten (Trockenware, Tiefkuehlware, Getraenke, ...): ein Tag vor
    Lagerbeginn, damit sie in einem Rutsch eingekauft werden koennen statt taeglich.
    """
    if entry.meal_date is None:
        return None
    if _is_shelf_stable(ingredient):
        if camp_year.start_date is not None:
            return camp_year.start_date - timedelta(days=1)
        return entry.meal_date
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
    aggregates: dict[tuple[int, str], _Aggregate] = {}

    for entry in camp_year.meal_plan_entries:
        if entry.recipe is None or entry.status == "abgesagt":
            continue
        portions = entry.planned_portions or entry.recipe.default_portions
        if not portions:
            continue
        base_portions = entry.recipe.default_portions or portions
        factor = Decimal(portions) / Decimal(base_portions)

        for item in entry.recipe.ingredients:
            key = (item.ingredient_id, item.unit)
            aggregate = aggregates.setdefault(key, _Aggregate(ingredient_id=item.ingredient_id, unit=item.unit))
            aggregate.quantity += item.quantity * factor
            aggregate.recipe_names.add(entry.recipe.name)
            if entry.meal_date is not None:
                aggregate.needed_dates.add(entry.meal_date)
            if assign_shopping_dates:
                shopping_date = entry.shopping_date or _derive_item_shopping_date(entry, item.ingredient, camp_year)
                if shopping_date:
                    aggregate.shopping_dates.add(shopping_date)

    shopping_list = ShoppingList(camp_year=camp_year, name=name or f"Einkaufsliste {camp_year.year}")
    session.add(shopping_list)

    for aggregate in aggregates.values():
        best_price = price_service.find_best_price(session, aggregate.ingredient_id, year=price_year)
        quantity = aggregate.quantity.quantize(Decimal("0.001"))
        estimated_total = (quantity * best_price.price_per_unit).quantize(Decimal("0.01")) if best_price else None
        ingredient = best_price.ingredient if best_price else None

        shopping_list.items.append(
            ShoppingListItem(
                ingredient_id=aggregate.ingredient_id,
                quantity=quantity,
                unit=aggregate.unit,
                estimated_price_per_unit=best_price.price_per_unit if best_price else None,
                estimated_total_price=estimated_total,
                category=ingredient.category if ingredient else None,
                storage_type=ingredient.storage_type if ingredient else None,
                needed_date=min(aggregate.needed_dates) if aggregate.needed_dates else None,
                shopping_date=min(aggregate.shopping_dates) if aggregate.shopping_dates else None,
                status="offen",
                linked_recipes_text=", ".join(sorted(aggregate.recipe_names)),
            )
        )
    return shopping_list


def group_by_shopping_day(shopping_list: ShoppingList) -> dict[date | None, list[ShoppingListItem]]:
    groups: dict[date | None, list[ShoppingListItem]] = defaultdict(list)
    for item in shopping_list.items:
        groups[item.shopping_date].append(item)
    return dict(groups)


def group_by_category(shopping_list: ShoppingList) -> dict[str | None, list[ShoppingListItem]]:
    groups: dict[str | None, list[ShoppingListItem]] = defaultdict(list)
    for item in shopping_list.items:
        groups[item.category].append(item)
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


ALLOWED_ITEM_STATUSES = ("offen", "bestellt", "gekauft", "erledigt", "pruefen")


def set_item_status(item: ShoppingListItem, status: str) -> ShoppingListItem:
    if status not in ALLOWED_ITEM_STATUSES:
        raise ValueError(f"Ungültiger Status '{status}'. Erlaubt: {', '.join(ALLOWED_ITEM_STATUSES)}")
    item.status = status
    return item


def total_estimated_cost(shopping_list: ShoppingList) -> Decimal:
    return sum((item.estimated_total_price or Decimal("0") for item in shopping_list.items), Decimal("0"))


def delete_shopping_list(session, shopping_list: ShoppingList) -> None:
    session.delete(shopping_list)
    session.flush()
