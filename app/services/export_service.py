from __future__ import annotations

import csv
from pathlib import Path

from openpyxl import Workbook

from app.models import Recipe, ShoppingList

SHOPPING_LIST_COLUMNS = (
    "Zutat",
    "Menge",
    "Einheit",
    "Preis/Einheit",
    "Gesamtpreis",
    "Kategorie",
    "Einkaufstag",
    "Status",
    "Rezepte",
    "Notizen",
)


def _shopping_list_rows(shopping_list: ShoppingList) -> list[tuple]:
    rows = []
    for item in shopping_list.items:
        rows.append(
            (
                item.ingredient.name if item.ingredient else "",
                item.quantity,
                item.unit or "",
                item.estimated_price_per_unit or "",
                item.estimated_total_price or "",
                item.category or "",
                item.shopping_date.isoformat() if item.shopping_date else "",
                item.status or "",
                item.linked_recipes_text or "",
                item.notes or "",
            )
        )
    return rows


def export_shopping_list_to_csv(shopping_list: ShoppingList, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(SHOPPING_LIST_COLUMNS)
        writer.writerows(_shopping_list_rows(shopping_list))
    return path


def export_shopping_list_to_excel(shopping_list: ShoppingList, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = shopping_list.name[:31] or "Einkaufsliste"
    sheet.append(SHOPPING_LIST_COLUMNS)
    for row in _shopping_list_rows(shopping_list):
        sheet.append(row)
    workbook.save(path)
    return path


RECIPE_COLUMNS = ("Name", "Kategorie", "Mahlzeit", "Standardportionen", "Aktiv", "Notizen")


def export_recipes_to_csv(recipes: list[Recipe], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(RECIPE_COLUMNS)
        for recipe in recipes:
            writer.writerow(
                (
                    recipe.name,
                    recipe.category or "",
                    recipe.meal_type or "",
                    recipe.default_portions or "",
                    "Ja" if recipe.active else "Nein",
                    recipe.notes or "",
                )
            )
    return path
