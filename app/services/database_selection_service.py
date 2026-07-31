"""Entscheidet beim App-Start, welche Datenbank-Engine benutzt wird, wenn eine Cloud-Verbindung
konfiguriert ist: direkt die Cloud, oder - falls sie gerade nicht erreichbar ist bzw. noch
ungesyncte Offline-Aenderungen vorliegen - der lokale Offline-Cache (siehe sync_service).

Der rein lokale SQLite-Modus (keine Cloud konfiguriert) bleibt unveraendert in main.py, da er
keine dieser Entscheidungen braucht.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import create_engine

from app.config import AppConfig
from app.db import check_connectivity, create_engine_from_config
from app.models import Base
from app.services import sync_service
from app.utils.paths import get_offline_cache_path, get_offline_sync_state_path


class OfflineWithoutCacheError(Exception):
    """Cloud nicht erreichbar und es existiert noch keine lokale Offline-Kopie - kann nur
    behoben werden, indem die App einmal mit Internetverbindung gestartet wird."""


@dataclass(slots=True)
class DatabaseSelection:
    config: AppConfig
    target_description: str
    is_offline_mode: bool
    cloud_database_url: str | None


def resolve_cloud_or_offline_mode(project_root: Path, saved_url: str) -> DatabaseSelection:
    cloud_config = AppConfig.load(project_root=project_root, database_url=saved_url)
    cloud_engine = create_engine_from_config(cloud_config)
    cloud_reachable = check_connectivity(cloud_engine) == "ok"

    offline_cache_path = get_offline_cache_path()
    sync_state_path = get_offline_sync_state_path()

    if cloud_reachable and offline_cache_path.exists():
        cache_engine = create_engine(f"sqlite:///{offline_cache_path.as_posix()}", future=True)
        try:
            Base.metadata.create_all(cache_engine)
            last_synced_at = sync_service.read_last_synced_at(sync_state_path)
            plan = sync_service.analyze(cache_engine, cloud_engine, last_synced_at)
        finally:
            cache_engine.dispose()

        if not plan.new_rows and not plan.updated_rows and not plan.conflicts:
            # Rein lesend verglichen und nichts Ungesynctes gefunden - der Cache ist nur noch
            # ein veralteter Spiegel, sicher loeschbar (kein offener Handle in diesem Prozess).
            offline_cache_path.unlink(missing_ok=True)
            sync_state_path.unlink(missing_ok=True)
        else:
            return DatabaseSelection(
                config=AppConfig.load(project_root=project_root, database_path=offline_cache_path),
                target_description="Offline-Modus (ungesyncte Änderungen vorhanden)",
                is_offline_mode=True,
                cloud_database_url=saved_url,
            )

    if cloud_reachable:
        return DatabaseSelection(
            config=cloud_config,
            target_description="Cloud-Datenbank (Neon Postgres)",
            is_offline_mode=False,
            cloud_database_url=saved_url,
        )

    if offline_cache_path.exists():
        return DatabaseSelection(
            config=AppConfig.load(project_root=project_root, database_path=offline_cache_path),
            target_description="Offline-Modus (keine Internetverbindung)",
            is_offline_mode=True,
            cloud_database_url=saved_url,
        )

    raise OfflineWithoutCacheError(
        "Die Cloud-Datenbank ist nicht erreichbar und es liegt noch keine lokale Offline-Kopie "
        "vor. Bitte die Anwendung einmal mit Internetverbindung starten."
    )
