from __future__ import annotations

import csv
from pathlib import Path
from xml.sax.saxutils import escape

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Recipe, ShoppingList
from app.services import shopping_service
from app.services.recipe_service import RecipeCostResult, UNASSIGNED_COMPONENT_LABEL

SHOPPING_LIST_COLUMNS = (
    "Zutat",
    "Menge",
    "Einheit",
    "Preis/Einheit",
    "Gesamtpreis",
    "Kategorie",
    "Händler",
    "Bedarfsdatum",
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
                item.store or "",
                shopping_service.format_date_de(item.needed_date),
                shopping_service.format_date_de(item.shopping_date),
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


# --- Rezept-PDF (druckfähige Rezeptkarte) --------------------------------------------

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
LOGO_PATH = ASSETS_DIR / "kolping_logo.jpeg"

PDF_ORANGE = colors.HexColor("#FF8C00")
PDF_ORANGE_TINT = colors.HexColor("#FFF1E0")
PDF_TEXT_DARK = colors.HexColor("#2F2C2A")
PDF_TEXT_MUTED = colors.HexColor("#6B6864")
PDF_BORDER = colors.HexColor("#E0DFDD")
PDF_CRITICAL = colors.HexColor("#B3261E")


def _pdf_text(value: str | None) -> str:
    return escape(value) if value else ""


def _group_cost_lines(recipe: Recipe, cost_result: RecipeCostResult) -> list[tuple[str, list]]:
    """Gruppiert die Kostenzeilen in der Reihenfolge der Teilstuecke (plus 'Sonstiges' am Ende, falls noetig)."""
    order = [component.name for component in recipe.components]
    if any(line.component_name == UNASSIGNED_COMPONENT_LABEL for line in cost_result.lines):
        order.append(UNASSIGNED_COMPONENT_LABEL)

    grouped: dict[str, list] = {name: [] for name in order}
    for line in cost_result.lines:
        grouped.setdefault(line.component_name, []).append(line)
        if line.component_name not in order:
            order.append(line.component_name)
    return [(name, grouped[name]) for name in order if grouped[name]]


def _pdf_logo_header(meta_lines: list[str]) -> Table:
    """Kopfzeile fuer PDF-Exporte: Kolping-Logo links, Metadaten rechts."""
    meta_style = ParagraphStyle("PdfMeta", parent=getSampleStyleSheet()["Normal"], textColor=PDF_TEXT_DARK, fontSize=10, leading=14)
    logo_cell = ""
    if LOGO_PATH.exists():
        image_width, image_height = ImageReader(str(LOGO_PATH)).getSize()
        width = 42 * mm
        height = width * image_height / image_width
        logo_cell = Image(str(LOGO_PATH), width=width, height=height)

    meta_cell = Paragraph("<br/>".join(meta_lines), meta_style)
    header_table = Table([[logo_cell, meta_cell]], colWidths=[90 * mm, None])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOX", (1, 0), (1, 0), 0.75, PDF_BORDER),
                ("INNERPADDING", (1, 0), (1, 0), 6),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
            ]
        )
    )
    return header_table


def export_recipe_to_pdf(recipe: Recipe, cost_result: RecipeCostResult, path: Path) -> Path:
    """Exportiert ein Rezept als druckfähige, nach Teilstücken gegliederte Rezeptkarte."""
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title=recipe.name,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "RecipeTitle", parent=styles["Title"], textColor=PDF_TEXT_DARK, fontSize=24, alignment=TA_CENTER, spaceAfter=2
    )
    meta_style = ParagraphStyle("RecipeMeta", parent=styles["Normal"], textColor=PDF_TEXT_DARK, fontSize=10, leading=14)
    heading_style = ParagraphStyle("SectionHeading", parent=styles["Heading2"], textColor=PDF_TEXT_DARK, fontSize=13, spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], textColor=PDF_TEXT_DARK, fontSize=10, leading=15)
    muted_style = ParagraphStyle("Muted", parent=styles["Normal"], textColor=PDF_TEXT_MUTED, fontSize=9)

    story = []

    meta_lines = [f"<b>Kategorie:</b> {_pdf_text(recipe.category) or '-'}", f"<b>Mahlzeit:</b> {_pdf_text(recipe.meal_type) or '-'}"]
    story.append(_pdf_logo_header(meta_lines))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(_pdf_text(recipe.name), title_style))
    story.append(
        Paragraph(
            f"Portionen: <b>{cost_result.portions}</b>",
            ParagraphStyle("Portions", parent=meta_style, alignment=TA_CENTER, fontSize=12, spaceAfter=6),
        )
    )
    story.append(Spacer(1, 4 * mm))

    column_widths = [70 * mm, 22 * mm, 22 * mm, 28 * mm, 28 * mm]
    for component_name, lines in _group_cost_lines(recipe, cost_result):
        band = Table([[Paragraph(_pdf_text(component_name), ParagraphStyle("Band", parent=styles["Normal"], textColor=colors.white, fontSize=11, leading=13))]], colWidths=[sum(column_widths)])
        band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), PDF_ORANGE), ("LEFTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        story.append(band)

        table_data = [["Zutat", "Menge", "Einheit", "Preis/Einheit", "Gesamtpreis"]]
        for line in lines:
            price_text = f"{line.price_per_unit:.2f} EUR" if line.price_per_unit is not None else "fehlt"
            cost_text = f"{line.line_cost:.2f} EUR" if line.line_cost is not None else "-"
            table_data.append([line.ingredient_name, str(line.quantity), line.unit, price_text, cost_text])

        ingredient_table = Table(table_data, colWidths=column_widths, repeatRows=1)
        table_style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), PDF_ORANGE_TINT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, -1), PDF_TEXT_DARK),
            ("GRID", (0, 0), (-1, -1), 0.5, PDF_BORDER),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        for row_index, line in enumerate(lines, start=1):
            if line.price_per_unit is None:
                table_style_commands.append(("TEXTCOLOR", (3, row_index), (4, row_index), PDF_CRITICAL))
            if row_index % 2 == 0:
                table_style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#FCFCFB")))
        ingredient_table.setStyle(TableStyle(table_style_commands))
        story.append(ingredient_table)
        story.append(Spacer(1, 4 * mm))

    summary_text = f"<b>Gesamtkosten: {cost_result.total_cost:.2f} EUR</b>"
    if cost_result.cost_per_portion is not None:
        summary_text += f" &nbsp;|&nbsp; <b>Preis pro Portion: {cost_result.cost_per_portion:.2f} EUR</b>"
    story.append(Paragraph(summary_text, ParagraphStyle("Summary", parent=body_style, fontSize=12, spaceBefore=2)))
    if cost_result.missing_price_ingredients:
        missing_text = "Achtung, fehlende Preise: " + ", ".join(_pdf_text(name) for name in cost_result.missing_price_ingredients)
        story.append(Paragraph(missing_text, ParagraphStyle("Missing", parent=muted_style, textColor=PDF_CRITICAL, spaceBefore=2)))

    if recipe.steps:
        story.append(Paragraph("Zubereitung", heading_style))
        total_minutes = sum(step.duration_minutes or 0 for step in recipe.steps)
        if total_minutes:
            story.append(Paragraph(f"Gesamtdauer: ca. {total_minutes} Min.", muted_style))
        step_style = ParagraphStyle("Step", parent=body_style, spaceAfter=6)
        for index, step in enumerate(sorted(recipe.steps, key=lambda s: s.sort_order), start=1):
            title = _pdf_text(step.title) or f"Schritt {index}"
            duration_text = f" ({step.duration_minutes} Min.)" if step.duration_minutes else ""
            step_html = f"<b>{index}. {title}{duration_text}</b>"
            if step.description:
                step_html += f"<br/>{_pdf_text(step.description)}"
            story.append(Paragraph(step_html, step_style))
    elif recipe.instructions:
        story.append(Paragraph("Zubereitung", heading_style))
        instructions_html = _pdf_text(recipe.instructions).replace("\n", "<br/>")
        story.append(Paragraph(instructions_html, body_style))

    if recipe.notes:
        story.append(Paragraph("Notizen", heading_style))
        story.append(Paragraph(_pdf_text(recipe.notes).replace("\n", "<br/>"), body_style))

    doc.build(story)
    return path


# --- Einkaufslisten-PDF (druckfähige Checkliste) -------------------------------------

SHOPPING_PDF_GROUPINGS = ("none", "day", "store")


def export_shopping_list_to_pdf(shopping_list: ShoppingList, path: Path, group_by: str = "none") -> Path:
    """Exportiert eine Einkaufsliste als druckfähige Checkliste, optional nach Einkaufstag oder Händler gruppiert."""
    if group_by not in SHOPPING_PDF_GROUPINGS:
        raise ValueError(f"Ungültige Gruppierung '{group_by}'. Erlaubt: {', '.join(SHOPPING_PDF_GROUPINGS)}")
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        title=shopping_list.name,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ShoppingTitle", parent=styles["Title"], textColor=PDF_TEXT_DARK, fontSize=22, alignment=TA_CENTER, spaceAfter=2
    )
    band_style = ParagraphStyle("Band", parent=styles["Normal"], textColor=colors.white, fontSize=11, leading=13)
    body_style = ParagraphStyle("Body", parent=styles["Normal"], textColor=PDF_TEXT_DARK, fontSize=10, leading=15)
    muted_style = ParagraphStyle("Muted", parent=styles["Normal"], textColor=PDF_TEXT_MUTED, fontSize=9)

    story = []

    camp_year = shopping_list.camp_year
    meta_lines = [f"<b>Camp-Jahr:</b> {_pdf_text(camp_year.name) if camp_year else '-'}", f"<b>Erstellt:</b> {shopping_list.generated_at:%d.%m.%Y %H:%M}"]
    story.append(_pdf_logo_header(meta_lines))
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(_pdf_text(shopping_list.name), title_style))
    story.append(Spacer(1, 4 * mm))

    if group_by == "day":
        groups: list[tuple[object, list]] = list(shopping_service.grouped_by_day_ordered(shopping_list))
        group_labels = [shopping_service.format_shopping_day_label(key) for key, _ in groups]
    elif group_by == "store":
        groups = list(shopping_service.grouped_by_store_ordered(shopping_list))
        group_labels = [key or shopping_service.UNASSIGNED_STORE_LABEL for key, _ in groups]
    else:
        groups = [(None, list(shopping_list.items))]
        group_labels = [None]

    column_widths = [8 * mm, 78 * mm, 22 * mm, 20 * mm, 30 * mm]
    header_row = ["", "Zutat", "Menge", "Einheit", "Gesamtpreis"]

    for (_key, items), label in zip(groups, group_labels):
        if not items:
            continue
        if label is not None:
            band = Table([[Paragraph(_pdf_text(label), band_style)]], colWidths=[sum(column_widths)])
            band.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), PDF_ORANGE),
                        ("LEFTPADDING", (0, 0), (-1, -1), 6),
                        ("TOPPADDING", (0, 0), (-1, -1), 4),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ]
                )
            )
            story.append(band)

        table_data = [header_row]
        for item in items:
            name = item.ingredient.name if item.ingredient else ""
            price_text = f"{item.estimated_total_price:.2f} EUR" if item.estimated_total_price is not None else "-"
            table_data.append(["", name, str(item.quantity), item.unit or "", price_text])

        item_table = Table(table_data, colWidths=column_widths, repeatRows=1)
        style_commands = [
            ("BACKGROUND", (0, 0), (-1, 0), PDF_ORANGE_TINT),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, -1), PDF_TEXT_DARK),
            ("GRID", (0, 0), (-1, -1), 0.5, PDF_BORDER),
            ("ALIGN", (2, 0), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("BOX", (0, 1), (0, -1), 1, PDF_TEXT_DARK),
        ]
        for row_index, item in enumerate(items, start=1):
            if item.estimated_price_per_unit is None:
                style_commands.append(("TEXTCOLOR", (4, row_index), (4, row_index), PDF_CRITICAL))
            if row_index % 2 == 0:
                style_commands.append(("BACKGROUND", (0, row_index), (-1, row_index), colors.HexColor("#FCFCFB")))
        item_table.setStyle(TableStyle(style_commands))
        story.append(item_table)
        story.append(Spacer(1, 4 * mm))

    total = shopping_service.total_estimated_cost(shopping_list)
    story.append(Paragraph(f"<b>Gesamtsumme (geschätzt): {total:.2f} EUR</b>", ParagraphStyle("Summary", parent=body_style, fontSize=12, spaceBefore=2)))

    missing = sorted({item.ingredient.name for item in shopping_list.items if item.ingredient and item.estimated_price_per_unit is None})
    if missing:
        missing_text = "Achtung, fehlende Preise: " + ", ".join(_pdf_text(name) for name in missing)
        story.append(Paragraph(missing_text, ParagraphStyle("Missing", parent=muted_style, textColor=PDF_CRITICAL, spaceBefore=2)))

    doc.build(story)
    return path
