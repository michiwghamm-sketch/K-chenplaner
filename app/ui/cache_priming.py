from __future__ import annotations

from PySide6.QtCore import QObject, QThread
from PySide6.QtWidgets import QWidget
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.models import Base
from app.services import sync_service
from app.utils.paths import get_offline_cache_path, get_offline_sync_state_path


class _CachePrimingWorker(QObject):
    def __init__(self, cloud_engine: Engine, thread: QThread) -> None:
        super().__init__()
        self._cloud_engine = cloud_engine
        self._thread = thread

    def run(self) -> None:
        # Best-effort: schlaegt der Hintergrund-Abgleich fehl (z. B. Verbindung waehrenddessen
        # weg), soll das die laufende Sitzung nicht stoeren - naechster Versuch beim naechsten Start.
        try:
            cache_engine = create_engine(f"sqlite:///{get_offline_cache_path().as_posix()}", future=True)
            try:
                Base.metadata.create_all(cache_engine)
                sync_service.refresh_local_cache_from_cloud(
                    cache_engine, self._cloud_engine, get_offline_sync_state_path()
                )
            finally:
                cache_engine.dispose()
        except Exception:  # noqa: BLE001 - Hintergrund-Wartung, darf die App nie zum Absturz bringen
            pass
        self._thread.quit()


def prime_offline_cache_async(parent: QWidget, cloud_engine: Engine) -> None:
    thread = QThread(parent)
    worker = _CachePrimingWorker(cloud_engine, thread)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
