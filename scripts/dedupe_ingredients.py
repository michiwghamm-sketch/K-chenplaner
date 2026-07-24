from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from app.db import initialize_database, session_scope  # noqa: E402
from app.models import Ingredient  # noqa: E402
from app.services import ingredient_service, validation_service  # noqa: E402
from app.services.backup_service import create_backup  # noqa: E402


@dataclass
class MergeLogEntry:
    keep_name: str
    remove_name: str
    reason: str
    similarity: float
    affected_recipes: list[str] = field(default_factory=list)


@dataclass
class ReviewCandidate:
    """Aehnliches Paar unterhalb der automatischen Schwelle - wird nie automatisch zusammengefuehrt."""

    name_a: str
    name_b: str
    similarity: float
    recipes_a: list[str] = field(default_factory=list)
    recipes_b: list[str] = field(default_factory=list)


@dataclass
class DedupeResult:
    merged: list[MergeLogEntry]
    review: list[ReviewCandidate]
    backup_path: Path | None


def run_dedupe(config: AppConfig, *, apply: bool) -> DedupeResult:
    """Findet und (falls apply=True) fuehrt hochsichere Zutaten-Dubletten zusammen.

    Kombiniert zwei hochsichere Kandidatenquellen, die automatisch angewendet werden:
    - find_alias_orphan_candidates(): ein Mensch hat die Zusammengehoerigkeit bereits per Alias
      bestaetigt, die Dublette wurde als Ingredient-Zeile aber nie geloescht (z. B. durch einen
      spaeteren Reimport, der den Vor-Merge-Zustand zurueckgebracht hat).
    - find_merge_candidates(): Singular/Plural-Regel oder >=93% Namensaehnlichkeit.

    Eine dritte, schwaechere Quelle (validation_service.find_duplicate_ingredients_without_alias(),
    88%) wird nur als "manuell zu pruefen" aufgelistet, nie automatisch zusammengefuehrt.

    Mit apply=False (Standard/Trockenlauf) wird die Datenbank nicht veraendert; es wird kein Backup
    erstellt. Mit apply=True wird vorher ein Backup angelegt (siehe backup_service.create_backup).
    """
    _, engine, session_factory = initialize_database(config)

    backup_path: Path | None = None
    if apply:
        backup_path = create_backup(config)

    with session_scope(session_factory) as session:
        # Mehrere Kandidatenquellen und Ketten von 3+ aehnlichen Zutaten (z. B. "Champignon"/
        # "Champignons"/"Champigons") koennen dieselbe Zutat mehrfach als 'remove' nennen, oder eine
        # bereits verschmolzene Zutat erneut aufgreifen. redirect verfolgt, wo eine (echt oder nur
        # gedanklich) zusammengefuehrte Zutat gelandet ist, damit spaetere Kandidaten immer zum
        # aktuellen Ueberlebenden aufgeloest werden - unabhaengig davon, ob apply=True ist, damit
        # Trockenlauf und echter Lauf dieselben (deduplizierten) Kandidaten berichten.
        redirect: dict[int, Ingredient] = {}

        def resolve(ingredient: Ingredient) -> Ingredient:
            while ingredient.id in redirect:
                ingredient = redirect[ingredient.id]
            return ingredient

        merged: list[MergeLogEntry] = []
        # Nur die exakten Paare, die tatsaechlich zusammengefuehrt wurden, sollen aus der
        # "manuell pruefen"-Liste rausgefiltert werden - nicht jedes Paar, das irgendeine der
        # beteiligten Zutaten beruehrt. Sonst verschwindet z. B. "Champingions" (eine dritte,
        # eigenstaendige Dublette von "Champigons") spurlos aus dem Bericht, nur weil "Champigons"
        # bereits an einem anderen Merge beteiligt war.
        handled_pair_keys: set[frozenset[int]] = set()

        combined_candidates = (
            ingredient_service.find_alias_orphan_candidates(session) + ingredient_service.find_merge_candidates(session)
        )
        for candidate in combined_candidates:
            handled_pair_keys.add(frozenset((candidate.keep.id, candidate.remove.id)))

            actual_keep = resolve(candidate.keep)
            actual_remove = resolve(candidate.remove)
            if actual_keep.id == actual_remove.id:
                continue  # bereits ueber eine andere Kandidatenquelle/Kette konsolidiert

            affected_recipes = ingredient_service.describe_recipe_usage(actual_remove)
            merged.append(
                MergeLogEntry(
                    keep_name=actual_keep.name,
                    remove_name=actual_remove.name,
                    reason=candidate.reason,
                    similarity=candidate.similarity,
                    affected_recipes=affected_recipes,
                )
            )
            redirect[actual_remove.id] = actual_keep
            if apply:
                ingredient_service.merge_ingredients(session, keep=actual_keep, remove=actual_remove)

        review: list[ReviewCandidate] = []
        seen_review_pairs: set[frozenset[int]] = set()

        def add_review(first: Ingredient, second: Ingredient, *, similarity: float) -> None:
            pair_key = frozenset((first.id, second.id))
            if pair_key in handled_pair_keys or pair_key in seen_review_pairs:
                return
            seen_review_pairs.add(pair_key)
            review.append(
                ReviewCandidate(
                    name_a=first.name,
                    name_b=second.name,
                    similarity=similarity,
                    recipes_a=ingredient_service.describe_recipe_usage(first),
                    recipes_b=ingredient_service.describe_recipe_usage(second),
                )
            )

        for first, second, similarity in validation_service.find_duplicate_ingredients_without_alias(session):
            add_review(first, second, similarity=similarity)

    return DedupeResult(merged=merged, review=review, backup_path=backup_path)


def write_report(project_root: Path, result: DedupeResult, *, applied: bool) -> Path:
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    report_path = docs_dir / "ingredient_merge_report.md"

    lines = [
        "# Zutaten-Zusammenfuehrung",
        "",
        f"- Ausgefuehrt am: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Modus: {'angewendet' if applied else 'Trockenlauf (nichts geaendert)'}",
        f"- Backup: {result.backup_path if result.backup_path else '(kein Backup, Trockenlauf)'}",
        f"- Automatisch zusammengefuehrte Dubletten: {len(result.merged)}",
        f"- Manuell zu pruefende Kandidaten: {len(result.review)}",
        "",
    ]
    if not result.merged:
        lines.append("Keine hochsicheren Dubletten gefunden.")
    else:
        lines.append("| Behalten | Zusammengefuehrt (jetzt Alias) | Grund | Ähnlichkeit | Betroffene Rezepte |")
        lines.append("| --- | --- | --- | --- | --- |")
        for entry in result.merged:
            recipes = "<br>".join(entry.affected_recipes) if entry.affected_recipes else "(keine)"
            lines.append(
                f"| {entry.keep_name} | {entry.remove_name} | {entry.reason} | {entry.similarity:.0%} | {recipes} |"
            )

    lines += ["", "## Manuell zu pruefen", ""]
    if not result.review:
        lines.append("Keine weiteren Kandidaten unterhalb der automatischen Schwelle gefunden.")
    else:
        lines.append(
            "Diese Paare sind sich aehnlich, aber nicht sicher genug fuer eine automatische "
            "Zusammenfuehrung. Bitte in der Zutatenverwaltung pruefen und bei Bedarf manuell "
            "zusammenfuehren."
        )
        lines.append("")
        lines.append("| Zutat A | Zutat B | Ähnlichkeit | Rezepte A | Rezepte B |")
        lines.append("| --- | --- | --- | --- | --- |")
        for candidate in result.review:
            recipes_a = "<br>".join(candidate.recipes_a) if candidate.recipes_a else "(keine)"
            recipes_b = "<br>".join(candidate.recipes_b) if candidate.recipes_b else "(keine)"
            lines.append(
                f"| {candidate.name_a} | {candidate.name_b} | {candidate.similarity:.0%} | {recipes_a} | {recipes_b} |"
            )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Findet und fuehrt hochsichere Zutaten-Dubletten zusammen.")
    parser.add_argument("--db-path", help="Optionaler Pfad zur SQLite-Datenbank.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aenderungen wirklich anwenden (legt vorher automatisch ein Backup an). Ohne dieses "
        "Flag passiert nur ein Trockenlauf, es wird nichts gespeichert.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Veraltet: ein Lauf ohne --apply ist bereits ein Trockenlauf. Nur fuer Abwaertskompatibilitaet.",
    )
    args = parser.parse_args()

    if args.dry_run and args.apply:
        parser.error("--dry-run und --apply schliessen sich gegenseitig aus.")
    if args.dry_run:
        print("Hinweis: --dry-run ist nicht mehr noetig, ein Lauf ohne --apply ist bereits ein Trockenlauf.")

    config = AppConfig.load(project_root=PROJECT_ROOT, database_path=Path(args.db_path) if args.db_path else None)
    result = run_dedupe(config, apply=args.apply)
    report_path = write_report(PROJECT_ROOT, result, applied=args.apply)

    print(f"Datenbank: {config.database_path}")
    print(f"Modus: {'angewendet' if args.apply else 'Trockenlauf'}")
    if result.backup_path:
        print(f"Backup erstellt: {result.backup_path}")
    print(f"Automatisch zusammengefuehrte Paare: {len(result.merged)}")
    for entry in result.merged:
        print(f"  {entry.remove_name!r} -> {entry.keep_name!r} ({entry.reason}, {entry.similarity:.0%})")
        for recipe in entry.affected_recipes:
            print(f"      betrifft Rezept: {recipe}")
    print(f"Manuell zu pruefende Paare: {len(result.review)}")
    for candidate in result.review:
        print(f"  {candidate.name_a!r} <-> {candidate.name_b!r} ({candidate.similarity:.0%})")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
