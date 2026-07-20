from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from app.models import CampYear, ShoppingList, ShoppingListItem
from app.services import price_service


@dataclass(slots=True)
class _Aggregate:
    ingredient_id: int
    unit: str
    quantity: Decimal = Decimal("0")
    recipe_names: set[str] = field(default_factory=set)
    shopping_dates: set[date] = field(default_factory=set)


def generate_shopping_list(
    session,
    camp_year: CampYear,
    *,
    name: str | None = None,
    price_year: int | None = None,
) -> ShoppingList:
    """Aggregiert alle geplanten (nicht abgesagten) Mahlzeiten eines Camp-Jahrs zu einer Einkaufsliste."""
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
            if entry.shopping_date:
                aggregate.shopping_dates.add(entry.shopping_date)

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


def filter_by_store(shopping_list: ShoppingList, store: str) -> list[ShoppingListItem]:
    return [item for item in shopping_list.items if item.store == store]


ALLOWED_ITEM_STATUSES = ("offen", "bestellt", "gekauft", "erledigt", "pruefen")


def set_item_status(item: ShoppingListItem, status: str) -> ShoppingListItem:
    if status not in ALLOWED_ITEM_STATUSES:
        raise ValueError(f"Ungueltiger Status '{status}'. Erlaubt: {', '.join(ALLOWED_ITEM_STATUSES)}")
    item.status = status
    return item


def total_estimated_cost(shopping_list: ShoppingList) -> Decimal:
    return sum((item.estimated_total_price or Decimal("0") for item in shopping_list.items), Decimal("0"))
