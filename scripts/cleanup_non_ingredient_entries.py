from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.config import AppConfig
from app.db import initialize_database, session_scope
from app.main import load_saved_database_path
from app.services.backup_service import create_backup
from app.services.data_cleanup_service import cleanup_non_ingredient_entries


def main() -> int:
    saved_path = load_saved_database_path()
    config = AppConfig.load(project_root=PROJECT_ROOT, database_path=saved_path) if saved_path else AppConfig.load(project_root=PROJECT_ROOT)
    _, _, session_factory = initialize_database(config)

    backup_path = create_backup(config)
    with session_scope(session_factory) as session:
        report = cleanup_non_ingredient_entries(session)

    print(f"Backup erstellt: {backup_path}")
    print(f"Geloeschte Einkaufs-Summenzeilen: {report.deleted_shopping_summary_count}")
    print(f"Geloeschte Nicht-Zutaten: {len(report.deleted_ingredient_names)}")
    for name in report.deleted_ingredient_names:
        print(f"- {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
