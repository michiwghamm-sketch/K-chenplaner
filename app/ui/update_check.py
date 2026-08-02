from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QWidget

from app import __version__
from app.services.update_service import UpdateCheckError, UpdateInfo, check_for_update


class _UpdateCheckWorker(QObject):
    finished = Signal(object)  # UpdateInfo | None
    failed = Signal(str)

    def __init__(self, *, report_errors: bool) -> None:
        super().__init__()
        self.report_errors = report_errors

    def run(self) -> None:
        try:
            self.finished.emit(check_for_update(__version__, raise_on_error=self.report_errors))
        except UpdateCheckError as exc:
            self.failed.emit(str(exc))


def run_update_check_async(
    parent: QWidget,
    on_result: Callable[[UpdateInfo | None], None],
    *,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Fuehrt den Update-Check in einem Hintergrund-Thread aus (HTTP-Request soll die UI nie
    blockieren) und ruft `on_result` im UI-Thread mit dem Ergebnis auf."""
    thread = QThread(parent)
    worker = _UpdateCheckWorker(report_errors=on_error is not None)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)

    def _handle_result(result: UpdateInfo | None) -> None:
        on_result(result)
        thread.quit()

    def _handle_error(message: str) -> None:
        if on_error is not None:
            on_error(message)
        thread.quit()

    worker.finished.connect(_handle_result)
    worker.failed.connect(_handle_error)
    thread.finished.connect(worker.deleteLater)
    thread.finished.connect(thread.deleteLater)
    thread.start()
