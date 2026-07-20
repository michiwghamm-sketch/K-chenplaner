# Technical Notes

## Phase 1 Vorgehen

Die aktuelle Umgebung stellte weder `python` noch `git` direkt im `PATH` bereit. Fuer die Analyse der bestehenden `.xlsm`-Datei wurde deshalb die OOXML-Struktur direkt gelesen:

- `xl/workbook.xml` fuer Blattliste
- `xl/_rels/workbook.xml.rels` fuer Blatt-Mapping
- `xl/sharedStrings.xml` fuer Textinhalte
- `xl/worksheets/*.xml` fuer Tabellenstrukturen, Header und Formeln

## Konsequenz

Die in `docs/migration_report.md` und `docs/import_mapping.md` dokumentierten Ergebnisse basieren auf einer echten Dateianalyse, aber nicht auf einer ausgefuehrten Python-Laufzeit in dieser Umgebung.

## Phase 4/5: Laufzeitumgebung

Zum Zeitpunkt von Phase 4 war in der Entwicklungsumgebung weiterhin kein nutzbares `python`/`py` im `PATH` vorhanden (nur ein Microsoft-Store-Alias-Stub sowie aeltere Anaconda-Umgebungen mit Python 3.8, zu alt fuer SQLAlchemy 2.0/PySide6). Geloest durch:

```powershell
winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements -e
```

Danach wurde ein projektlokales virtuelles Environment unter `.venv/` angelegt und `requirements.txt` dort installiert. Alle `pytest`- und App-Laeufe in dieser Umgebung verwenden `.venv\Scripts\python.exe` (siehe README, Abschnitt "Entwickler-Setup").

## UI-Framework: Wechsel zu PySide6

Der urspruengliche Plan sah CustomTkinter vor. Auf Wunsch wurde stattdessen **PySide6 (Qt 6)** gewaehlt. Auswirkungen:

- `requirements.txt`: `customtkinter` durch `PySide6>=6.7` ersetzt; `pandas` entfernt, da im Code nirgends importiert (Excel-Import laeuft ausschliesslich ueber `openpyxl`).
- UI-Struktur folgt weiterhin der geplanten Modulaufteilung (`app/ui/*_view.py`), nur mit Qt-Widgets (`QMainWindow`, `QStackedWidget`, `QTableWidget`, `QDialog`-Formulare) statt CustomTkinter-Widgets.
- Jede View haelt keine offene Datenbank-Session; stattdessen oeffnet jede Aktion eine kurze Session ueber `AppContext.session()` (Context-Manager um `app.db.session_scope`), fuehrt die Aenderung aus und committet sofort. Das vermeidet lang lebende Transaktionen und macht jede Aktion einzeln nachvollziehbar.

## UI-Tests: Vorgehen ohne verlaessliche GUI-Automatisierung

Mausklicks per `SetCursorPos`/`mouse_event` in dieser Windows-Umgebung sind unzuverlaessig, weil VS Code/Terminal-Fenster den Fokus stehlen koennen und Screenshot- vs. Bildschirmkoordinaten durch DPI-Skalierung leicht abweichen. Deshalb wurde zusaetzlich zu einem manuellen Start (Screenshot-Verifikation mit echten migrierten Daten) ein **headless Smoke-Test** gebaut:

- startet `QApplication` mit `QT_QPA_PLATFORM=offscreen`
- kopiert die echte Projekt-Datenbank in eine temporaere Datei (keine Schreibzugriffe auf Produktivdaten)
- baut `MainWindow` (konstruiert alle neun Views) und ruft anschliessend `_show_page()` fuer jeden Navigationseintrag auf, mit vollstaendigem Traceback bei Fehlern

Dieser Test faengt echte Konstruktions-/Refresh-Fehler zuverlaessig ab und ist reproduzierbar (kein Maus-/Fokus-Risiko). Empfehlung: bei zukuenftigen UI-Aenderungen dieses Muster wiederverwenden, bevor auf manuelle Klicktests vertraut wird.

