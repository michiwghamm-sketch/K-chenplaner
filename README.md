# Zeltlager Verpflegung

Desktop-Anwendung zur Migration und langfristigen Ablösung einer Excel-basierten Verpflegungsplanung fuer Zeltlager.

## Projektziel

Das Projekt ueberfuehrt eine bestehende Excel-Arbeitsmappe in eine installierbare Python-Desktop-App mit spaeterer Datenbankbasis. Phase 1 konzentriert sich bewusst nur auf die strukturierte Analyse der vorhandenen Excel-Datei.

## Aktueller Stand

- Phase 1 (Excel-Inspektion) abgeschlossen:
  - [`scripts/inspect_excel.py`](scripts/inspect_excel.py)
  - [`docs/migration_report.md`](docs/migration_report.md)
  - [`docs/import_mapping.md`](docs/import_mapping.md)
  - [`docs/excel_inspection_report.json`](docs/excel_inspection_report.json)
  - [`docs/vba_analysis.md`](docs/vba_analysis.md)
  - [`docs/vba_functionality_map.md`](docs/vba_functionality_map.md)
- Phase 2 (Datenmodell/DB) abgeschlossen:
  - SQLAlchemy-Konfiguration in [`app/config.py`](app/config.py)
  - Datenbankinitialisierung in [`app/db.py`](app/db.py)
  - relationales Datenmodell in [`app/models.py`](app/models.py), siehe [`docs/data_model.md`](docs/data_model.md)
- Phase 3 (Excel-Migration) abgeschlossen:
  - [`scripts/migrate_excel_to_sqlite.py`](scripts/migrate_excel_to_sqlite.py), Report unter [`docs/import_run_report.md`](docs/import_run_report.md)
- Phase 4 (Fachlogik-Services) abgeschlossen:
  - Services unter [`app/services/`](app/services) (Rezeptskalierung/-kosten, Preisermittlung, Einkaufsaggregation, Feedback, Validierung, Backup/Restore, Import/Export)
- Phase 5 (UI-Prototyp) abgeschlossen:
  - Desktop-UI mit **PySide6 (Qt 6)** unter [`app/ui/`](app/ui) - alle neun Module (Dashboard, Wochenplan, Rezepte, Zutaten, Preise, Einkaufsliste, Feedback, Import/Export, Einstellungen)
  - Design angelehnt an [kolpingjugend-regensburg.de](https://www.kolpingjugend-regensburg.de/) (Farben, Typografie), siehe [`app/ui/theme.py`](app/ui/theme.py)
  - Wochenplan-Raster statt Jahresplanung (ein Camp-Jahr = eine Zeltlagerwoche), Tagesverantwortliche, meal-genaues Feedback
  - Rezepte mit Teilstuecken, Kosten je Zutat, Mengen-Historie/Skalierung und PDF-Export ([`app/assets/kolping_logo.jpeg`](app/assets/kolping_logo.jpeg))
  - siehe [`docs/user_guide.md`](docs/user_guide.md)
- Phase 6 (Installer/Build) noch offen.
- Testsuite: `pytest` unter [`tests/`](tests) (siehe "Tests ausfuehren").

## Entwickler-Setup

1. Python 3.12 oder neuer installieren (Windows: `winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements -e`, falls kein `python`/`py` im `PATH` verfuegbar ist).
2. Git installieren oder den vorhandenen Git-for-Windows-Pfad nutzen.
3. Virtuelle Umgebung anlegen:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Git Setup

Die Schritt-fuer-Schritt-Anleitung steht in [`docs/git_setup.md`](docs/git_setup.md).

## App starten

```powershell
.venv\Scripts\python.exe app\main.py
```

Beim ersten Start fragt die App nach einem Datenbankpfad (siehe [`docs/user_guide.md`](docs/user_guide.md)). Der Pfad wird unter `%APPDATA%\ZelaKueche\settings.json` gespeichert und beim naechsten Start wiederverwendet.

## Excel inspizieren

```powershell
.venv\Scripts\python.exe scripts\inspect_excel.py
```

Optional mit explizitem Pfad:

```powershell
.venv\Scripts\python.exe scripts\inspect_excel.py --workbook data\zeltlager_verpflegung.xlsx
```

## Migration ausfuehren

```powershell
.venv\Scripts\python.exe scripts\migrate_excel_to_sqlite.py
```

Der Import ist defensiv: unklare Werte werden als Import-Issue protokolliert statt verworfen, bestehende Daten werden nicht stillschweigend ueberschrieben. Ergebnis unter [`docs/import_run_report.md`](docs/import_run_report.md) / `.json`. Kann auch aus der App heraus unter **Import/Export** erneut angestossen werden.

Der Import erkennt zusaetzlich Teilstuecke (Rezept-Unterabschnitte wie "Soße") anhand der
im Excel ueber mehrere Zeilen verbundenen Zellen neben der Zutatentabelle, und importiert
Zutatenzeilen ohne Einheit/Menge (z. B. Gewuerze "nach Geschmack") statt sie stillschweigend
zu ueberspringen - siehe `docs/import_run_report.md` fuer die Details je Zeile.

## Zutaten-Dubletten zusammenfuehren

```powershell
.venv\Scripts\python.exe scripts\dedupe_ingredients.py --dry-run   # nur anzeigen
.venv\Scripts\python.exe scripts\dedupe_ingredients.py             # anwenden
```

Findet hochsichere Zutaten-Dubletten (Singular/Plural wie "Zwiebel"/"Zwiebeln", eindeutige
Tippfehler) und fuehrt sie zusammen: die zusammengefuehrte Zutat wird zum Alias, alle
Rezepte/Preise/Einkaufslisten-Positionen werden umgehaengt. Report unter
[`docs/ingredient_merge_report.md`](docs/ingredient_merge_report.md). Vor dem Anwenden
empfiehlt sich ein Backup (siehe unten).

## Tests ausfuehren

```powershell
.venv\Scripts\python.exe -m pytest
```

## Build erstellen

Noch nicht implementiert. Geplant ist ein Build mit PyInstaller ueber [`scripts/build_exe.py`](scripts/build_exe.py).

## Datenbank initialisieren

Die Datenbank wird beim App-Start automatisch erzeugt (Tabellen ueber `app.db.initialize_database`). Fuer eigene Skripte/Tests kann `AppConfig.load(...)` + `initialize_database(...)` direkt verwendet werden.

## SQLite auf Drive-Laufwerken

SQLite-Dateien auf OneDrive, Dropbox, Google Drive oder Netzlaufwerken koennen bei Synchronisation und gleichzeitiger Nutzung beschaedigt werden. Die spaetere App wird deshalb:

- einen frei waehlbaren Datenbankpfad unterstuetzen
- vor problematischen Speicherorten warnen
- Backup- und Restore-Funktionen anbieten
- keine echte Mehrbenutzer-Gleichzeitigkeit mit SQLite versprechen

## Backup und Restore

Ueber die App unter **Import/Export**, oder direkt per Service:

- `app.services.backup_service.create_backup(config)` kopiert die SQLite-Datei zeitgestempelt nach `backups/`.
- `restore_backup(config, backup_path, confirm=True)` ersetzt die aktuelle Datenbank, sichert den bisherigen Stand vorher automatisch zusaetzlich und verlangt eine explizite Bestaetigung.
- `verify_integrity(engine)` fuehrt `PRAGMA integrity_check` aus.

Backups werden nicht committet (`backups/` steht in `.gitignore`).

## Bekannte Grenzen

- Die aktuelle Arbeitsmappe liegt in diesem Workspace nicht im erwarteten Ordner `data/`, sondern im Projektwurzelverzeichnis.
- `git` ist lokal vorhanden, aber in dieser Umgebung nicht im `PATH`. Der direkte Pfad zu Git for Windows kann verwendet werden.
- Das Standard-`python`/`py` im `PATH` war in dieser Umgebung urspruenglich nicht benutzbar; ein passendes Python 3.12 wurde per `winget` installiert und ein projektlokales `.venv` angelegt (siehe [`docs/technical_notes.md`](docs/technical_notes.md)).
- Die Tests setzen installierte Abhaengigkeiten aus `requirements.txt` voraus.
- Die UI ist ein Prototyp: kein PyInstaller-Build, keine Mehrbenutzer-Gleichzeitigkeit (SQLite), Einheiten werden bei der Einkaufsaggregation nicht automatisch umgerechnet.
