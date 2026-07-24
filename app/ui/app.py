from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStatusBar, QStackedWidget, QWidget

from app.context import AppContext
from app.ui.dashboard_view import DashboardView
from app.ui.feedback_view import FeedbackView
from app.ui.import_export_view import ImportExportView
from app.ui.ingredients_view import IngredientsView
from app.ui.navigation import NAV_ITEMS, Sidebar
from app.ui.planning_view import PlanningView
from app.ui.recipes_view import RecipesView
from app.ui.settings_view import SettingsView
from app.ui.shopping_view import ShoppingView
from app.utils.drive_detection import get_drive_warning

VIEW_CLASSES = {
    "dashboard": DashboardView,
    "planning": PlanningView,
    "recipes": RecipesView,
    "ingredients": IngredientsView,
    "shopping": ShoppingView,
    "feedback": FeedbackView,
    "import_export": ImportExportView,
    "settings": SettingsView,
}


class MainWindow(QMainWindow):
    """Hauptfenster: Seitenleiste, Modul-Bereich und Statusleiste."""

    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.setWindowTitle("Zeltlager Verpflegung")
        self.resize(1200, 800)

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

        self.setCentralWidget(central)

        status_bar = QStatusBar(self)
        self.setStatusBar(status_bar)
        db_status_text = f"Datenbank: {context.config.database_path}"
        warning = get_drive_warning(context.config.database_path)
        if warning:
            db_status_text += "  |  WARNUNG: Datenbank liegt auf einem Cloud-Sync- oder Netzlaufwerk."
        status_bar.showMessage(db_status_text)

        self._show_page("dashboard")

    def _show_page(self, key: str) -> None:
        page = self._pages.get(key)
        if page is None:
            return
        self.stack.setCurrentWidget(page)
        if hasattr(page, "refresh"):
            page.refresh()
