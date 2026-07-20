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

## Leichtgewichtige Schema-Migration ohne Alembic

Als `recipe_feedback.meal_plan_entry_id`/`quantity_sufficient` fuers Wochenplan-Feedback ergaenzt wurden, schlug der Start gegen die bereits bestehende Produktiv-Datenbank fehl: `Base.metadata.create_all()` legt nur komplett fehlende Tabellen an, aendert aber nie Spalten einer bereits existierenden Tabelle.

Geloest mit `app.db.sync_schema(engine)` (wird in `init_database` direkt nach `create_all()` aufgerufen):

- vergleicht fuer jede bereits bestehende Tabelle die Modell-Spalten mit den tatsaechlich vorhandenen Spalten (`sqlalchemy.inspect`)
- fehlende Spalten werden per `ALTER TABLE ... ADD COLUMN` ergaenzt
- ist eine neue Spalte als `unique=True` deklariert, wird zusaetzlich ein `CREATE UNIQUE INDEX IF NOT EXISTS` nachgezogen, weil SQLites `ADD COLUMN` keine UNIQUE-Constraints mitbringen kann

Das ist bewusst kein Ersatz fuer Alembic (keine Versionshistorie, keine Downgrades, keine Datentransformationen) - fuer rein additive, nullable Spalten in einer kleinen SQLite-App reicht es aber und vermeidet die zusaetzliche Abhaengigkeit. Sollte spaeter eine Spalte umbenannt, entfernt oder NOT-NULL-pflichtig werden, braucht es eine echte Migration.

## Re-Extraktion: Teilstuecke, fehlende Zutaten, Preislisten-Dubletten

Beim erneuten Durchlaufen des Excel-Imports (Teilstueck-Erkennung + Korrektur der zuvor
uebersprungenen Zutatenzeilen) kamen drei echte Bugs zum Vorschein, alle ueber Tests
abgesichert:

1. **`import_price_list` hatte keinerlei Duplikatspruefung.** Jeder erneute Lauf hat saemtliche
   Preislisten-Zeilen (anders als Rezeptzeilen, die ueber `sort_order`/`has_matching_price`
   erkennbar sind) ein weiteres Mal eingefuegt. Erst beim zweiten Testlauf gegen die echte
   Datenbank aufgefallen (z. B. "Butter" hatte danach 9 statt 7 Preiszeilen, exakte Duplikate
   mit Zeitstempeln von zwei verschiedenen Importlaeufen). Fix: Preis+Einheit+Jahr+Quelle wird
   vor dem Einfuegen geprueft (siehe `test_run_import_is_idempotent_for_price_list_rows`).
2. **Teilstueck-Erkennung verglich Label und Rezeptname exakt.** Ein einzelnes Label, das den
   kompletten Zutatenblock ueberspannt und nur den Rezeptnamen wiederholt, soll kein echtes
   Teilstueck werden (siehe `detect_recipe_components`). Der Vergleich schlug fehl, wenn das
   Label das Leerzeichen weglaesst (Rezept "Gemüse Nudeln", Label "Gemüsenudeln") - erst durch
   Pruefung der tatsaechlich importierten Daten sichtbar geworden, nicht durch die
   urspruengliche Testabdeckung. Fix: Vergleich ignoriert Leerzeichen.
3. **Zutaten-Zusammenfuehrung bei mehr als zwei aehnlichen Namen.** `find_merge_candidates`
   bildet Paare ueber eine feste Momentaufnahme; bei drei sich gegenseitig aehnlichen Namen
   (z. B. "Champignon"/"Champignons"/"Champigons") koennen zwei Paare dieselbe Zutat als
   "wird entfernt" markieren. Ohne Gegenmassnahme fuehrt das zweite Merge zu einem
   `session.delete()` auf ein bereits geloeschtes bzw. (bei anderer Reihenfolge) noch nicht
   gespeichertes Objekt. Fix in `scripts/dedupe_ingredients.py`: ein `redirect`-Dict loest jeden
   Kandidaten auf den tatsaechlich noch existierenden Nachfolger auf, bevor gemerged wird
   (siehe `test_apply_handles_triangle_of_similar_ingredients_without_error`).

Alle drei Bugs wurden erst durch Ausfuehren gegen die echte Datenbank sichtbar, nicht durch
die urspruengliche (synthetische) Testabdeckung - ein Hinweis darauf, Migrations-/Bereinigungs-
Skripte nach jeder Aenderung einmal per `--dry-run` bzw. gegen eine Kopie der echten Datenbank
laufen zu lassen, bevor sie auf die Produktivdatei angewendet werden.

