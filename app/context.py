from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig
from app.db import session_scope


@dataclass
class AppContext:
    """Buendelt Konfiguration, Engine und Session-Factory fuer die UI-Schicht."""

    config: AppConfig
    engine: Engine
    session_factory: sessionmaker[Session]
    current_camp_year_id: int | None = None
    # Gesetzt, sobald irgendwann eine Cloud-Verbindung konfiguriert wurde (siehe
    # database_selection_service) - auch waehrend die App gerade im Offline-Cache laeuft.
    cloud_database_url: str | None = None
    is_offline_mode: bool = False

    @contextmanager
    def session(self) -> Iterator[Session]:
        with session_scope(self.session_factory) as session:
            yield session
