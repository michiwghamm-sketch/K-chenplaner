# Zeltlager Verpflegung

Desktop-Anwendung zur Migration und langfristigen Ablösung einer Excel-basierten Verpflegungsplanung fuer Zeltlager.

## Projektziel

Das Projekt ueberfuehrt eine bestehende Excel-Arbeitsmappe in eine installierbare Python-Desktop-App mit spaeterer Datenbankbasis. Phase 1 konzentriert sich bewusst nur auf die strukturierte Analyse der vorhandenen Excel-Datei.

## Aktueller Stand

- Projektgrundstruktur angelegt
- Phase 1 abgeschlossen:
  - [`scripts/inspect_excel.py`](scripts/inspect_excel.py)
  - [`docs/migration_report.md`](docs/migration_report.md)
  - [`docs/import_mapping.md`](docs/import_mapping.md)
  - [`docs/excel_inspection_report.json`](docs/excel_inspection_report.json)
  - [`docs/vba_analysis.md`](docs/vba_analysis.md)
  - [`docs/vba_functionality_map.md`](docs/vba_functionality_map.md)
- Phase 2 begonnen:
  - SQLAlchemy-Konfiguration in [`app/config.py`](app/config.py)
  - Datenbankinitialisierung in [`app/db.py`](app/db.py)
  - relationales Datenmodell in [`app/models.py`](app/models.py)
  - erste DB-Tests unter [`tests/`](tests)

## Entwickler-Setup

1. Python 3.12 oder neuer installieren.
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

Die Desktop-App wird erst in spaeteren Phasen implementiert. Die aktuellen App-Dateien sind nur ein bewusst schlankes Grundgeruest.

## Excel inspizieren

```powershell
py -3.12 scripts\inspect_excel.py
```

Optional mit explizitem Pfad:

```powershell
py -3.12 scripts\inspect_excel.py --workbook data\zeltlager_verpflegung.xlsx
```

## Migration ausfuehren

Noch nicht implementiert. Diese Phase folgt nach Bestaetigung des Datenmodells und Abschluss der Importlogik.

## Tests ausfuehren

```powershell
pytest
```

## Build erstellen

Noch nicht implementiert. Geplant ist ein Build mit PyInstaller.

## Datenbank initialisieren

Die Datenbank wird spaeter beim App-Start automatisch erzeugt. Fuer lokale Experimente kann die Phase-2-Basis bereits aus `app.db` initialisiert werden.

## SQLite auf Drive-Laufwerken

SQLite-Dateien auf OneDrive, Dropbox, Google Drive oder Netzlaufwerken koennen bei Synchronisation und gleichzeitiger Nutzung beschaedigt werden. Die spaetere App wird deshalb:

- einen frei waehlbaren Datenbankpfad unterstuetzen
- vor problematischen Speicherorten warnen
- Backup- und Restore-Funktionen anbieten
- keine echte Mehrbenutzer-Gleichzeitigkeit mit SQLite versprechen

## Backup und Restore

Noch nicht implementiert. In Phase 2/3 werden dafuer Services und UI-Hinweise vorbereitet.

## Bekannte Grenzen

- Die aktuelle Arbeitsmappe liegt in diesem Workspace nicht im erwarteten Ordner `data/`, sondern im Projektwurzelverzeichnis.
- `git` ist lokal vorhanden, aber in dieser Umgebung nicht im `PATH`. Der direkte Pfad zu Git for Windows kann verwendet werden.
- Das Standard-`python` im `PATH` war in dieser Umgebung nicht benutzbar; Analysen wurden daher mit einem alternativen lokalen Interpreter ausgefuehrt.
- Die Tests setzen installierte Abhaengigkeiten aus `requirements.txt` voraus.
