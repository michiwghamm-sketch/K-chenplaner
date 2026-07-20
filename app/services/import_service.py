from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AppConfig  # noqa: E402
from scripts.inspect_excel import find_excel_file  # noqa: E402
from scripts.migrate_excel_to_sqlite import ImportCounters, ImportIssueRecord, run_import  # noqa: E402


def run_excel_import(
    config: AppConfig,
    *,
    excel_path: Path | None = None,
) -> tuple[ImportCounters, list[ImportIssueRecord], Path]:
    """Fuehrt den Excel-Import fuer die UI aus und liefert Zaehler, Issues und den verwendeten Quellpfad zurueck."""
    resolved_excel_path = excel_path or find_excel_file(config.project_root, None)
    counters, issues = run_import(resolved_excel_path, config)
    return counters, issues, resolved_excel_path


def get_last_import_report(config: AppConfig) -> dict | None:
    report_path = config.docs_dir / "import_run_report.json"
    if not report_path.exists():
        return None
    return json.loads(report_path.read_text(encoding="utf-8"))
