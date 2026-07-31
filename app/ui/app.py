from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QMessageBox, QStatusBar, QStackedWidget, QWidget

from app.context import AppContext
from app.services.update_service import UpdateInfo
from app.ui.dashboard_view import DashboardView
from app.ui.feedback_view import FeedbackView
from app.ui.import_export_view import ImportExportView
from app.ui.ingredients_view import IngredientsView
from app.ui.navigation import NAV_ITEMS, Sidebar
from app.ui.open_prices_view import OpenPricesView
from app.ui.planning_view import PlanningView
from app.ui.recipes_view import RecipesView
from app.ui.settings_view import SettingsView
from app.ui.shopping_view import ShoppingView
from app.ui.cache_priming import prime_offline_cache_async
from app.ui.update_check import run_update_check_async
from app.utils.drive_detection import get_drive_warning

VIEW_CLASSES = {
    "dashboard": DashboardView,
    "planning": PlanningView,
    "recipes": RecipesView,
    "ingredients": IngredientsView,
    "open_prices": OpenPricesView,
    "shopping": ShoppingView,
    "feedback": FeedbackView,
    "import_export": ImportExportView,
    "settings": SettingsView,
}


class MainWindow(QMainWindow):
    """Hauptfenster: Seitenleiste, Modul-Bereich und Statusleiste."""

    # Kleinste Fenstergroesse, bei der die Inhalte (Formulare, Tabellen, Diagramme) noch
    # sinnvoll nutzbar bleiben - darunter duerfte selbst mit Scroll-Bereichen zu wenig
    # Platz fuer eine brauchbare Bedienung sein.
    MIN_WIDTH = 1000
    MIN_HEIGHT = 650

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.setWindowTitle("Zeltlager Verpflegung")
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self._apply_initial_geometry()

        central = QWidget(self)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self.sidebar = Sidebar(central)
        self.sidebar.page_selected.connect(self._show_page)
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget(central)
        self._pages: dict[str, QWidget] = {}
        for key, _label in NAV_ITEMS:
            page = VIEW_CLASSES[key](context, self.stack)
            self._pages[key] = page
            self.stack.addWidget(page)
        layout.addWidget(self.stack)

        dashboard_page = self._pages.get("dashboard")
        if dashboard_page is not None and hasattr(dashboard_page, "navigate_requested"):
            dashboard_page.navigate_requested.connect(self._show_page)

        self.setCentralWidget(central)

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        if context.is_offline_mode:
            db_status_text = (
                f"Offline-Modus: {context.config.database_path}  |  "
                "Ungesyncte Änderungen - siehe Einstellungen > Jetzt synchronisieren"
            )
        elif context.config.is_sqlite:
            db_status_text = f"Datenbank: {context.config.database_path}"
            warning = get_drive_warning(context.config.database_path)
            if warning:
                db_status_text += "  |  WARNUNG: Datenbank liegt auf einem Cloud-Sync- oder Netzlaufwerk."
        else:
            db_status_text = "Datenbank: Cloud (Neon Postgres)"
        status_bar.showMessage(db_status_text)

        self._show_page("dashboard")

        # Verzoegert und im Hintergrund, damit ein langsames/fehlendes Internet den Start nie
        # ausbremst - bei Erfolg nur benachrichtigen, wenn es wirklich eine neuere Version gibt.
        QTimer.singleShot(2000, lambda: run_update_check_async(self, self._on_update_check_result))

        # Im Live-Cloud-Modus den Offline-Cache im Hintergrund auf dem aktuellen Stand halten,
        # damit ein spaeterer Internetausfall nahtlos in den Offline-Modus uebergehen kann.
        if context.cloud_database_url and not context.is_offline_mode:
            QTimer.singleShot(3000, lambda: prime_offline_cache_async(self, context.engine))

    def _on_update_check_result(self, update_info: UpdateInfo | None) -> None:
        if update_info is None:
            return
        result = QMessageBox.information(
            self,
            "Update verfügbar",
            f"Eine neuere Version ist verfügbar: {update_info.latest_version}\n\n"
            "Jetzt die Release-Seite zum Herunterladen öffnen?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if result == QMessageBox.StandardButton.Yes:
            QDesktopServices.openUrl(QUrl(update_info.download_url))

    def _apply_initial_geometry(self) -> None:
        """Startgroesse an den tatsaechlichen Bildschirm anpassen (85% der verfuegbaren Flaeche,
        zentriert), statt eine feste Pixelgroesse zu erzwingen - auf einem 14"-Notebook waere
        1200x800 ggf. zu gross (oder zu klein im Vergleich zu einem 27"-Monitor). Qt skaliert
        logische Pixel bereits automatisch nach dem DPI-Faktor des Bildschirms; hier geht es nur
        um einen sinnvollen Ausschnitt der verfuegbaren (bereits DPI-bereinigten) Flaeche.
        """
        screen = self.screen() or QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1200, 800)
            return

        available = screen.availableGeometry()
        width = min(max(int(available.width() * 0.85), self.MIN_WIDTH), available.width())
        height = min(max(int(available.height() * 0.85), self.MIN_HEIGHT), available.height())
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def _show_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        if hasattr(page, "refresh"):
            page.refresh()

        # Bei programmatischer Navigation (z. B. Klick auf einen Dashboard-Hinweis) muss die
        # Seitenleisten-Markierung mitziehen - sonst zeigt sie noch "Dashboard" an, waehrend
        # bereits eine andere Seite sichtbar ist. blockSignals verhindert, dass das Setzen hier
        # selbst wieder page_selected ausloest (waere ein harmloser, aber unnoetiger Re-Eintritt).
        for row in range(self.sidebar.count()):
            if self.sidebar.item(row).data(1000) == key:
                self.sidebar.blockSignals(True)
                self.sidebar.setCurrentRow(row)
                self.sidebar.blockSignals(False)
                break
