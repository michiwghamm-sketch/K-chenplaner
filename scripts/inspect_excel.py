from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

KEYWORDS = {
    "recipe": {
        "sheet": ["rezept", "fruehstueck", "frühstück", "mittag", "abend", "salat", "suppe", "curry"],
        "header": ["zutat", "zutaten", "menge", "portion", "preis", "kosten", "anleitung", "hinweis"],
    },
    "price_list": {
        "sheet": ["preis", "preisliste", "kosten", "quelle"],
        "header": ["preis", "einheit", "quelle", "laden", "shop", "stand", "notiz"],
    },
    "shopping_list": {
        "sheet": ["einkauf", "bestellung", "lager"],
        "header": ["artikel", "zutat", "gesamtpreis", "einkaufstag", "status", "laden", "menge"],
    },
    "planning": {
        "sheet": ["planung", "plan", "jahr", "woche", "tag"],
        "header": ["datum", "wochentag", "mahlzeit", "rezept", "portionen", "zielgruppe", "status"],
    },
    "feedback": {
        "sheet": ["feedback", "bewertung", "erfahrung", "rueckmeldung", "rückmeldung"],
        "header": ["bewertung", "wiederholen", "portionen gekocht", "rest", "was lief gut", "aendern", "ändern"],
    },
}


@dataclass
class ProblemCell:
    cell: str
    issue: str
    raw_value: str | None = None


@dataclass
class DetectedBlock:
    start_row: int
    end_row: int
    column_count: int
    non_empty_cells: int
    header_candidates: list[str] = field(default_factory=list)


@dataclass
class SheetReport:
    name: str
    path: str
    kind: str
    score: int
    used_range: str
    row_count: int
    column_count: int
    formula_count: int
    merged_ranges: list[str]
    tables: list[str]
    header_rows: list[dict[str, Any]]
    blocks: list[DetectedBlock]
    problem_cells: list[ProblemCell]
    notes: list[str]


def normalize_text(value: str) -> str:
    text = value.strip().lower()
    replacements = {
        "ä": "ae",
        "ö": "oe",
        "ü": "ue",
        "ß": "ss",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text)


def find_excel_file(project_root: Path, explicit_path: str | None) -> Path:
    if explicit_path:
        path = Path(explicit_path)
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            raise FileNotFoundError(f"Excel-Datei nicht gefunden: {path}")
        return path

    candidates: list[Path] = []
    for folder in [project_root / "data", project_root]:
        if not folder.exists():
            continue
        candidates.extend(sorted(folder.glob("*.xlsx")))
        candidates.extend(sorted(folder.glob("*.xlsm")))

    unique_candidates = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve())
        if key not in seen:
            unique_candidates.append(candidate)
            seen.add(key)

    if not unique_candidates:
        raise FileNotFoundError("Keine Excel-Datei in ./data oder im Projektwurzelverzeichnis gefunden.")
    if len(unique_candidates) > 1:
        names = ", ".join(path.name for path in unique_candidates)
        raise RuntimeError(f"Mehrere Excel-Dateien gefunden. Bitte --excel-path angeben. Kandidaten: {names}")
    return unique_candidates[0]


def read_xml(zip_file: ZipFile, path: str) -> ET.Element:
    with zip_file.open(path) as handle:
        return ET.fromstring(handle.read())


def load_shared_strings(zip_file: ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zip_file.namelist():
        return []
    root = read_xml(zip_file, "xl/sharedStrings.xml")
    strings: list[str] = []
    for item in root.findall("main:si", NS):
        parts = [node.text or "" for node in item.findall(".//main:t", NS)]
        strings.append("".join(parts))
    return strings


def load_workbook_structure(zip_file: ZipFile) -> list[tuple[str, str]]:
    workbook = read_xml(zip_file, "xl/workbook.xml")
    relationships = read_xml(zip_file, "xl/_rels/workbook.xml.rels")
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in relationships.findall("pkgrel:Relationship", NS)
    }

    sheet_paths: list[tuple[str, str]] = []
    for sheet in workbook.findall("main:sheets/main:sheet", NS):
        name = sheet.attrib["name"]
        rel_id = sheet.attrib[f"{{{NS['rel']}}}id"]
        target = rel_map[rel_id].lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheet_paths.append((name, target))
    return sheet_paths


def get_sheet_relations(zip_file: ZipFile, sheet_path: str) -> tuple[list[str], list[str]]:
    path = Path(sheet_path)
    rels_path = f"{path.parent.as_posix()}/_rels/{path.name}.rels"
    if rels_path not in zip_file.namelist():
        return [], []

    rel_root = read_xml(zip_file, rels_path)
    table_targets: list[str] = []
    notes: list[str] = []
    for rel in rel_root.findall("pkgrel:Relationship", NS):
        rel_type = rel.attrib.get("Type", "")
        target = rel.attrib.get("Target", "")
        if rel_type.endswith("/table"):
            normalized = (path.parent / target).as_posix().replace("xl/xl/", "xl/")
            table_targets.append(normalized)
        else:
            notes.append(rel_type.rsplit("/", 1)[-1])
    return table_targets, notes


def cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    value_node = cell.find("main:v", NS)
    inline_text = cell.find("main:is/main:t", NS)
    cell_type = cell.attrib.get("t")
    if inline_text is not None:
        return inline_text.text or ""
    if value_node is None:
        return None
    raw = value_node.text or ""
    if cell_type == "s":
        try:
            return shared_strings[int(raw)]
        except (ValueError, IndexError):
            return raw
    if cell_type == "b":
        return "TRUE" if raw == "1" else "FALSE"
    return raw


def detect_header_rows(rows: list[list[str]], max_rows: int = 15) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:max_rows], start=1):
        non_empty = [value for value in row if value]
        if len(non_empty) < 2:
            continue
        text_cells = [value for value in non_empty if re.search(r"[A-Za-zÄÖÜäöüß]", value)]
        ratio = len(text_cells) / len(non_empty)
        if ratio >= 0.6:
            candidates.append(
                {
                    "row_index": index,
                    "values": non_empty[:12],
                    "text_ratio": round(ratio, 2),
                }
            )
    return candidates[:5]


def detect_blocks(rows: list[list[str]]) -> list[DetectedBlock]:
    blocks: list[DetectedBlock] = []
    start_row: int | None = None
    block_rows: list[tuple[int, list[str]]] = []

    def flush() -> None:
        nonlocal start_row, block_rows
        if not block_rows or start_row is None:
            return
        end_row = block_rows[-1][0]
        column_count = max((len([value for value in row if value]) for _, row in block_rows), default=0)
        non_empty_cells = sum(len([value for value in row if value]) for _, row in block_rows)
        header_candidates = []
        for _, row in block_rows[:3]:
            texts = [value for value in row if value][:8]
            if len(texts) >= 2:
                header_candidates.append(" | ".join(texts))
        blocks.append(
            DetectedBlock(
                start_row=start_row,
                end_row=end_row,
                column_count=column_count,
                non_empty_cells=non_empty_cells,
                header_candidates=header_candidates,
            )
        )
        start_row = None
        block_rows = []

    for index, row in enumerate(rows, start=1):
        filled = [value for value in row if value]
        if filled:
            if start_row is None:
                start_row = index
            block_rows.append((index, row))
        elif start_row is not None:
            flush()
    flush()
    return blocks


def classify_sheet(name: str, header_rows: list[dict[str, Any]]) -> tuple[str, int]:
    normalized_name = normalize_text(name)
    header_text = " ".join(
        normalize_text(str(value))
        for row in header_rows
        for value in row.get("values", [])
    )

    best_kind = "unknown"
    best_score = 0
    for kind, signals in KEYWORDS.items():
        score = 0
        score += sum(3 for token in signals["sheet"] if token in normalized_name)
        score += sum(2 for token in signals["header"] if token in header_text)
        if score > best_score:
            best_kind = kind
            best_score = score
    return best_kind, best_score


def summarize_formulas(formulas: list[str]) -> list[str]:
    summary: list[str] = []
    formula_blob = " ".join(formulas).upper()
    checks = {
        "SUM": "Summenbildung erkannt",
        "IF": "Bedingte Logik erkannt",
        "ROUND": "Rundungslogik erkannt",
        "VLOOKUP": "SVERWEIS/VLOOKUP erkannt",
        "XLOOKUP": "XVERWEIS/XLOOKUP erkannt",
        "INDEX": "INDEX-basierte Verweise erkannt",
        "MATCH": "VERGLEICH/MATCH erkannt",
    }
    for token, note in checks.items():
        if token in formula_blob:
            summary.append(note)
    if any("*" in formula or "/" in formula for formula in formulas):
        summary.append("Multiplikations- oder Divisionslogik erkannt")
    return summary


def inspect_sheet(zip_file: ZipFile, sheet_name: str, sheet_path: str, shared_strings: list[str]) -> SheetReport:
    root = read_xml(zip_file, sheet_path)
    rows: list[list[str]] = []
    formulas: list[str] = []
    problem_cells: list[ProblemCell] = []

    dimension = root.find("main:dimension", NS)
    used_range = dimension.attrib.get("ref", "unbekannt") if dimension is not None else "unbekannt"

    merged_ranges = [
        merge.attrib["ref"]
        for merge in root.findall("main:mergeCells/main:mergeCell", NS)
    ]

    for row in root.findall("main:sheetData/main:row", NS):
        cell_values: list[str] = []
        for cell in row.findall("main:c", NS):
            reference = cell.attrib.get("r", "?")
            formula_node = cell.find("main:f", NS)
            if formula_node is not None:
                formula_text = formula_node.text or ""
                formulas.append(formula_text)
                if any(token in formula_text.upper() for token in ["#REF!", "#VALUE!", "#NAME?", "#DIV/0!"]):
                    problem_cells.append(ProblemCell(reference, "Formelfehler in Formeltext", formula_text))

            value = cell_value(cell, shared_strings)
            if value is None:
                cell_values.append("")
                continue

            if isinstance(value, str) and value.startswith("#"):
                problem_cells.append(ProblemCell(reference, "Excel-Fehlerwert", value))

            text = str(value).strip()
            cell_values.append(text)
        rows.append(cell_values)

    header_rows = detect_header_rows(rows)
    kind, score = classify_sheet(sheet_name, header_rows)
    blocks = detect_blocks(rows)
    table_targets, relation_notes = get_sheet_relations(zip_file, sheet_path)

    notes = summarize_formulas(formulas)
    if merged_ranges:
        notes.append("Zusammengefuehrte Zellen vorhanden")
    if table_targets:
        notes.append("Excel-Tabellenobjekte vorhanden")
    for relation_note in relation_notes:
        if relation_note not in {"table"}:
            notes.append(f"Verknuepfung erkannt: {relation_note}")

    row_count = len(rows)
    column_count = max((len(row) for row in rows), default=0)
    return SheetReport(
        name=sheet_name,
        path=sheet_path,
        kind=kind,
        score=score,
        used_range=used_range,
        row_count=row_count,
        column_count=column_count,
        formula_count=len(formulas),
        merged_ranges=merged_ranges,
        tables=[Path(target).name for target in table_targets],
        header_rows=header_rows,
        blocks=blocks,
        problem_cells=problem_cells[:25],
        notes=sorted(set(notes)),
    )


def build_import_mapping(reports: list[SheetReport]) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "ingredients": [],
        "ingredient_prices": [],
        "recipes": [],
        "recipe_ingredients": [],
        "meal_plan_entries": [],
        "recipe_feedback": [],
        "shopping_list_items": [],
        "unclassified_sheets": [],
    }

    targets = {
        "recipe": ["recipes", "recipe_ingredients"],
        "price_list": ["ingredients", "ingredient_prices"],
        "shopping_list": ["shopping_list_items"],
        "planning": ["meal_plan_entries"],
        "feedback": ["recipe_feedback"],
    }

    for report in reports:
        if report.kind == "unknown":
            mapping["unclassified_sheets"].append(report.name)
            continue
        for key in targets.get(report.kind, []):
            mapping[key].append(
                {
                    "sheet": report.name,
                    "confidence": report.score,
                    "headers": [row["values"] for row in report.header_rows[:2]],
                }
            )
    return mapping


def write_markdown_report(
    output_path: Path,
    excel_path: Path,
    reports: list[SheetReport],
    import_mapping: dict[str, Any],
    has_vba: bool,
) -> None:
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    by_kind: dict[str, list[SheetReport]] = {}
    for report in reports:
        by_kind.setdefault(report.kind, []).append(report)

    lines = [
        "# Migrationsreport",
        "",
        f"- Quelle: `{excel_path.name}`",
        f"- Voller Pfad: `{excel_path}`",
        f"- Generiert am: `{generated_at}`",
        f"- Anzahl Sheets: `{len(reports)}`",
        f"- VBA/Makros erkannt: `{'ja' if has_vba else 'nein'}`",
        "",
        "## 1. Erkannte Sheets",
        "",
    ]
    for report in reports:
        lines.append(
            f"- `{report.name}`: Typ `{report.kind}`, Used Range `{report.used_range}`, "
            f"Zeilen `{report.row_count}`, Spalten `{report.column_count}`, Formeln `{report.formula_count}`"
        )

    lines.extend(["", "## 2. Erkannte Datenbloecke", ""])
    for report in reports:
        lines.append(f"### {report.name}")
        if not report.blocks:
            lines.append("- Keine zusammenhaengenden Datenbloecke erkannt")
            continue
        for block in report.blocks[:10]:
            headers = "; ".join(block.header_candidates) if block.header_candidates else "keine"
            lines.append(
                f"- Zeilen `{block.start_row}-{block.end_row}`, nicht-leere Zellen `{block.non_empty_cells}`, "
                f"Spalten `{block.column_count}`, Header-Kandidaten: {headers}"
            )

    section_map = [
        ("recipe", "3. Erkannte Rezeptblaetter"),
        ("price_list", "4. Erkannte Preislisten"),
        ("shopping_list", "5. Erkannte Einkaufslisten"),
        ("planning", "6. Erkannte Jahresplanung"),
        ("feedback", "7. Erkannte Feedback-Struktur"),
    ]
    for kind, title in section_map:
        lines.extend(["", f"## {title}", ""])
        items = by_kind.get(kind, [])
        if not items:
            lines.append("- Keine sicheren Treffer")
            continue
        for report in items:
            headers = ", ".join(
                " / ".join(str(value) for value in row["values"][:6])
                for row in report.header_rows[:2]
            ) or "keine"
            lines.append(f"- `{report.name}` (Score `{report.score}`), Header-Indizien: {headers}")

    lines.extend(["", "## 8. Formellogik, soweit ableitbar", ""])
    formula_notes = sorted({note for report in reports for note in report.notes if "erkannt" in note.lower()})
    if formula_notes:
        for note in formula_notes:
            lines.append(f"- {note}")
    else:
        lines.append("- Keine besondere Formellogik erkannt")

    lines.extend(["", "## 9. Risiken beim Import", ""])
    risks: list[str] = []
    if any(report.merged_ranges for report in reports):
        risks.append("Zusammengefuehrte Zellen koennen Header- oder Tabellenstrukturen verschleiern.")
    if any(report.formula_count for report in reports):
        risks.append("Formeln muessen fachlich nachgebaut werden; Werte allein reichen nicht fuer eine saubere Migration.")
    if any(report.kind == "unknown" for report in reports):
        risks.append("Mindestens ein Blatt konnte nicht sicher klassifiziert werden.")
    if any(report.problem_cells for report in reports):
        risks.append("Es wurden problematische Zellen oder Fehlerwerte gefunden.")
    if has_vba:
        risks.append("Die Arbeitsmappe enthaelt VBA/Makros; relevante Fachlogik koennte ausserhalb der Zellformeln liegen.")
    if not risks:
        risks.append("Keine unmittelbaren Strukturfehler erkannt; fachliche Detailpruefung bleibt trotzdem noetig.")
    for risk in risks:
        lines.append(f"- {risk}")

    lines.extend(["", "## 10. Offene Fragen", ""])
    questions = [
        "Welche Blattbereiche sind historisch und welche aktiv fuer das naechste Lagerjahr?",
        "Sollen Makros oder VBA-Logik fachlich mit migriert werden, falls sie relevante Berechnungen enthalten?",
        "Welche Einheiten duerfen automatisch aggregiert werden und wo sind Umrechnungen erforderlich?",
    ]
    for question in questions:
        lines.append(f"- {question}")

    lines.extend(["", "## Anhang: Import-Mapping-Vorschlag", ""])
    for key, entries in import_mapping.items():
        lines.append(f"### {key}")
        if not entries:
            lines.append("- Keine Zuordnung")
            continue
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    lines.append(
                        f"- Blatt `{entry['sheet']}` mit Confidence `{entry['confidence']}` "
                        f"und Headern `{entry['headers']}`"
                    )
                else:
                    lines.append(f"- {entry}")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_mapping_report(output_path: Path, import_mapping: dict[str, Any]) -> None:
    lines = [
        "# Import Mapping",
        "",
        "Vorschlag fuer die erste relationale Zuordnung aus der Excel-Struktur.",
        "",
    ]
    for entity, entries in import_mapping.items():
        lines.append(f"## {entity}")
        if not entries:
            lines.extend(["- Keine Zuordnung erkannt", ""])
            continue
        for entry in entries:
            if isinstance(entry, dict):
                lines.append(
                    f"- Blatt `{entry['sheet']}` mit Confidence `{entry['confidence']}` "
                    f"und Header-Indizien `{entry['headers']}`"
                )
            else:
                lines.append(f"- `{entry}`")
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def serialize_reports(
    excel_path: Path,
    reports: list[SheetReport],
    import_mapping: dict[str, Any],
    has_vba: bool,
) -> dict[str, Any]:
    return {
        "source_file": str(excel_path),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "has_vba": has_vba,
        "sheet_count": len(reports),
        "sheets": [
            {
                **asdict(report),
                "blocks": [asdict(block) for block in report.blocks],
                "problem_cells": [asdict(cell) for cell in report.problem_cells],
            }
            for report in reports
        ],
        "import_mapping": import_mapping,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect an Excel workbook and generate migration reports.")
    parser.add_argument("--excel-path", help="Optional path to the workbook.")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)

    excel_path = find_excel_file(project_root, args.excel_path)
    with ZipFile(excel_path) as zip_file:
        shared_strings = load_shared_strings(zip_file)
        workbook_structure = load_workbook_structure(zip_file)
        has_vba = "xl/vbaProject.bin" in zip_file.namelist()
        reports = [
            inspect_sheet(zip_file, sheet_name, sheet_path, shared_strings)
            for sheet_name, sheet_path in workbook_structure
        ]

    import_mapping = build_import_mapping(reports)
    report_json = serialize_reports(excel_path, reports, import_mapping, has_vba)

    write_markdown_report(docs_dir / "migration_report.md", excel_path, reports, import_mapping, has_vba)
    write_mapping_report(docs_dir / "import_mapping.md", import_mapping)
    (docs_dir / "excel_inspection_report.json").write_text(
        json.dumps(report_json, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Quelle: {excel_path}")
    print(f"Sheets erkannt: {len(reports)}")
    for report in reports:
        print(f"- {report.name}: {report.kind} (Score {report.score})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
