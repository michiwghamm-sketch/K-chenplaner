from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from app.db import initialize_database, session_scope  # noqa: E402
from app.models import Ingredient  # noqa: E402
from app.services import ingredient_service  # noqa: E402


@dataclass
class MergeLogEntry:
    keep_name: str
    remove_name: str
    reason: str
    similarity: float


def run_dedupe(config: AppConfig, *, apply: bool) -> list[MergeLogEntry]:
    """Findet und (falls apply=True) fuehrt hochsichere Zutaten-Dubletten zusammen.

    Mit apply=False (Trockenlauf) werden nur die Kandidaten aufgelistet, ohne die
    Datenbank zu veraendern - nuetzlich, um die Vorschlaege vor dem eigentlichen
    Zusammenfuehren zu pruefen.
    """
    _, engine, session_factory = initialize_database(config)
    log: list[MergeLogEntry] = []

    if not apply:
        # Reiner Trockenlauf: Kandidaten ermitteln, aber nie merge_ingredients() aufrufen,
        # damit garantiert nichts geschrieben wird (kein Rollback-Kunstgriff noetig).
        with session_scope(session_factory) as session:
            for candidate in ingredient_service.find_merge_candidates(session):
                log.append(
                    MergeLogEntry(
                        keep_name=candidate.keep.name,
                        remove_name=candidate.remove.name,
                        reason=candidate.reason,
                        similarity=candidate.similarity,
                    )
                )
        return log

    with session_scope(session_factory) as session:
        # find_merge_candidates() computes keep/remove pairs from a single upfront snapshot.
        # When 3+ ingredients are mutually similar (e.g. "Champignon"/"Champignons"/"Champigons"),
        # two independent pairs can name the same ingredient as 'remove'. redirect tracks where
        # an already-merged-away ingredient ended up, so later candidates resolve to the current
        # survivor instead of re-merging (or deleting) something that's already gone.
        redirect: dict[int, Ingredient] = {}

        def resolve(ingredient: Ingredient) -> Ingredient:
            while ingredient.id in redirect:
                ingredient = redirect[ingredient.id]
            return ingredient

        for candidate in ingredient_service.find_merge_candidates(session):
            actual_keep = resolve(candidate.keep)
            actual_remove = resolve(candidate.remove)
            if actual_keep.id == actual_remove.id:
                continue  # already consolidated via a different pair in this same run

            log.append(
                MergeLogEntry(
                    keep_name=actual_keep.name,
                    remove_name=actual_remove.name,
                    reason=candidate.reason,
                    similarity=candidate.similarity,
                )
            )
            ingredient_service.merge_ingredients(session, keep=actual_keep, remove=actual_remove)
            redirect[actual_remove.id] = actual_keep

    return log


def write_report(project_root: Path, log: list[MergeLogEntry], *, applied: bool) -> Path:
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    report_path = docs_dir / "ingredient_merge_report.md"

    lines = [
        "# Zutaten-Zusammenfuehrung",
        "",
        f"- Ausgefuehrt am: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        f"- Modus: {'angewendet' if applied else 'Trockenlauf (nichts geaendert)'}",
        f"- Gefundene Dubletten: {len(log)}",
        "",
    ]
    if not log:
        lines.append("Keine hochsicheren Dubletten gefunden.")
    else:
        lines.append("| Behalten | Zusammengefuehrt (jetzt Alias) | Grund | Ähnlichkeit |")
        lines.append("| --- | --- | --- | --- |")
        for entry in log:
            lines.append(f"| {entry.keep_name} | {entry.remove_name} | {entry.reason} | {entry.similarity:.0%} |")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Findet und fuehrt hochsichere Zutaten-Dubletten zusammen.")
    parser.add_argument("--db-path", help="Optionaler Pfad zur SQLite-Datenbank.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Nur anzeigen, was zusammengefuehrt wuerde, ohne zu speichern."
    )
    args = parser.parse_args()

    config = AppConfig.load(project_root=PROJECT_ROOT, database_path=Path(args.db_path) if args.db_path else None)
    log = run_dedupe(config, apply=not args.dry_run)
    report_path = write_report(PROJECT_ROOT, log, applied=not args.dry_run)

    print(f"Datenbank: {config.database_path}")
    print(f"Modus: {'angewendet' if not args.dry_run else 'Trockenlauf'}")
    print(f"Zusammengefuehrte Paare: {len(log)}")
    for entry in log:
        print(f"  {entry.remove_name!r} -> {entry.keep_name!r} ({entry.reason}, {entry.similarity:.0%})")
    print(f"Report: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
