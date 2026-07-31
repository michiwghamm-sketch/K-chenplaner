from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QWidget

from app import __version__
from app.services.update_service import UpdateInfo, check_for_update


class _UpdateCheckWorker(QObject):
    finished = Signal(object)  # UpdateInfo | None

    def run(self) -> None:
        self.finished.emit(check_for_update(__version__))


def run_update_check_async(parent: QWidget, on_result: Callable[[UpdateInfo | None], None]) -> None:
    """Fuehrt den Update-Check in einem Hintergrund-Thread aus (HTTP-Request soll die UI nie
    blockieren) und ruft `on_result` im UI-Thread mit dem Ergebnis auf."""
    thread = QThread(parent)
    worker = _UpdateCheckWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def _handle_result(result: UpdateInfo | None) -> None:
        on_result(result)
        thread.quit()

    worker.finished.connect(_handle_result)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
