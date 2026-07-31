# ZelaKüche – Verpflegungsplanung fürs Zeltlager

Windows-Desktop-App für die Küchenplanung im Kolping-Zeltlager: Rezepte, Wochenplan,
Zutaten & Preise, Einkaufslisten und Feedback nach dem Lager - an einem Ort statt verteilt
über Excel-Dateien. Optional kann die Datenbank in einer kostenlosen Cloud-Datenbank liegen,
damit mehrere Leute gleichzeitig daran arbeiten.

## Was die App kann

- **Wochenplan**: Rasteransicht der Zeltlagerwoche (Tag × Mahlzeit), mit Tagesverantwortlichen
- **Rezepte**: Teilstücke, Mengen-Historie/Skalierung, Kosten je Zutat, PDF-Export
- **Zutaten & Preise**: Preisrecherche über Open Prices (Barcode-Suche)
- **Einkaufsliste**: automatisch aus dem Wochenplan generiert, gruppiert nach Laden/Einkaufstag
- **Feedback**: Rückmeldung je Rezept und Zeltlagerjahr (kam's an, Menge passend, Notizen)
- **Dashboard**: Überblick über das aktuelle Zeltlagerjahr

## Installation

1. Aktuelles Setup von der Releases-Seite herunterladen:
   **https://github.com/michiwghamm-sketch/K-chenplaner/releases/latest**
   (Datei `ZelaKueche-Setup.exe`, ca. 50 MB)
2. `ZelaKueche-Setup.exe` ausführen. Braucht **keine Admin-Rechte** (installiert nur für den
   eigenen Nutzer-Account nach `%LOCALAPPDATA%\Programs\ZelaKueche`) - falls Windows/der
   Virenscanner vor einer unbekannten .exe warnt: "Weitere Informationen" > "Trotzdem ausführen"
   (die App ist nicht code-signiert, das ist bei einer kleinen kostenlosen Vereins-App normal).
3. App über das neue Startmenü-Symbol "ZelaKueche" öffnen.
4. Beim allerersten Start fragt die App nach einem Speicherort für die Datenbank - den
   vorgeschlagenen Pfad einfach mit "Speichern" bestätigen. Das reicht für den Soloeinsatz.

Zum Deinstallieren: Windows-Einstellungen > Apps > "ZelaKueche" > Deinstallieren (oder
Startmenü-Ordner "ZelaKueche" > Uninstall).

## Gemeinsam an einer Datenbank arbeiten (Team-Modus)

Standardmäßig legt jede installierte App ihre eigene lokale Datenbank an - gut zum
Ausprobieren, aber jeder sieht nur seine eigenen Einträge. Für ein Team, das gemeinsam am
selben Wochenplan arbeitet, gibt es eine kostenlose Cloud-Datenbank (Neon Postgres):

1. Von der Person, die die Cloud-Datenbank eingerichtet hat, den **Connection-String**
   bekommen (sieht aus wie `postgresql://...`). **Diesen String wie ein Passwort behandeln** -
   nicht in Gruppenchats posten, nur direkt privat weitergeben. Er ist der einzige
   Zugangsschutz zur gemeinsamen Datenbank.
2. In der App: **Einstellungen > "Mit Cloud-Datenbank verbinden..."** > String einfügen >
   Anwendung neu starten.
3. Fertig - alle mit demselben Connection-String sehen und bearbeiten denselben Wochenplan,
   Änderungen sind sofort für alle sichtbar.

Wie man eine eigene Cloud-Datenbank für ein neues Team einrichtet, steht unter
["Cloud-Datenbank einrichten" weiter unten](#cloud-datenbank-einrichten-für-entwickleradmins).

### Offline arbeiten

Der Team-Modus braucht **nicht** durchgehend Internet. Ist die Cloud-Datenbank beim Start nicht
erreichbar (z. B. schlechtes Netz im Zeltlager), wechselt die App automatisch in einen lokalen
Offline-Cache - man kann normal weiterarbeiten, nur eben ohne dass andere die Änderungen sofort
sehen. Sobald wieder Internet da ist, zeigen die Einstellungen einen Button
**"Jetzt synchronisieren"**.

Wichtig zu wissen:

- Wurde derselbe Eintrag **sowohl offline als auch von jemand anderem in der Cloud** verändert,
  fragt die App beim Sync nach, welche Version gelten soll - nichts wird stillschweigend
  überschrieben.
- Offline gelöschte Einträge werden beim Sync **nicht** als Löschung übertragen - sie tauchen
  danach wieder auf, wenn sie in der Cloud noch existieren. Lieber ein ungewollt
  wieder­aufgetauchter Eintrag als ein versehentlich verlorener.

## Worauf man sonst achten sollte

- **Lokale Datenbank nicht in einem synchronisierten Ordner** (OneDrive, Google Drive, Dropbox)
  ablegen, wenn mehrere Leute/Geräte gleichzeitig darauf zugreifen könnten - die App warnt davor,
  aber gleichzeitiges Schreiben kann die Datei beschädigen. Für "mehrere Leute gleichzeitig" ist
  der Cloud-Modus (siehe oben) der richtige Weg, nicht ein geteilter Ordner.
- **Backups**: unter **Export & Backup** manuell erstellbar (nur im lokalen Modus - die
  Cloud-Datenbank sichert Neon automatisch, siehe deren Dashboard für Point-in-Time-Restore).
- **Updates**: die App prüft automatisch kurz nach dem Start (und manuell über
  **Einstellungen > "Nach Updates suchen"**), ob es eine neuere Version gibt, und verlinkt dann
  auf die Releases-Seite zum Herunterladen. Kein automatisches Selbst-Update - neue Version
  einfach wie oben herunterladen und drüberinstallieren.

## Cloud-Datenbank einrichten (für Entwickler/Admins)

Nur nötig, wenn noch keine gemeinsame Cloud-Datenbank existiert:

1. Kostenlosen Account auf [neon.tech](https://neon.tech) anlegen, Projekt + Datenbank
   erstellen.
2. Einen eigenen, eingeschränkten Datenbank-Nutzer für die App anlegen (nicht den
   Neon-Admin-Nutzer verwenden) und dessen Connection-String kopieren.
3. Falls schon lokal Daten erfasst wurden, einmalig migrieren:

   ```powershell
   .venv\Scripts\python.exe scripts\migrate_sqlite_to_postgres.py --sqlite-path instance\zeltlager_kueche.sqlite3 --postgres-url "postgresql://user:pw@host/dbname"
   ```

4. Connection-String an die Team-Mitglieder weitergeben (siehe Sicherheitshinweis oben) - jede:r
   trägt ihn unter Einstellungen ein.

## Für Entwickler

### Setup

1. Python 3.12+ installieren (Windows: `winget install --id Python.Python.3.12 --source winget --accept-package-agreements --accept-source-agreements -e`).
2. Virtuelle Umgebung anlegen:

   ```powershell
   py -3.12 -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Git-Setup: siehe [`docs/git_setup.md`](docs/git_setup.md).

### App aus dem Quellcode starten

```powershell
.venv\Scripts\python.exe app\main.py
```

Oder per Doppelklick auf `start_app.bat`.

### Tests ausführen

```powershell
.venv\Scripts\python.exe -m pytest
```

### Windows-Installer bauen

```powershell
.venv\Scripts\python.exe scripts\build_exe.py
```

erzeugt `dist\ZelaKueche\ZelaKueche.exe` (PyInstaller). Danach mit
[Inno Setup](https://jrsoftware.org/isinfo.php) (`winget install --id JRSoftware.InnoSetup -e`)
zu einem Setup packen:

```powershell
& "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe" installer\zelakueche.iss
```

Ergebnis: `Output\ZelaKueche-Setup.exe`. Für ein neues Release: Versionsnummer in
`app/__init__.py` (`__version__`) und `installer/zelakueche.iss` (`MyAppVersion`) hochzählen,
neu bauen, als GitHub Release mit dem Setup als Anhang veröffentlichen (das ist auch die Quelle,
gegen die der Auto-Update-Check in der App prüft).

### Architektur-Kurzüberblick

- **PySide6 (Qt 6)** Desktop-UI unter [`app/ui/`](app/ui), Design angelehnt an
  [kolpingjugend-regensburg.de](https://www.kolpingjugend-regensburg.de/).
- **SQLAlchemy**-Datenmodell in [`app/models.py`](app/models.py), siehe
  [`docs/data_model.md`](docs/data_model.md). Datenbank-Setup in
  [`app/config.py`](app/config.py) / [`app/db.py`](app/db.py) - unterstützt lokales SQLite
  und Postgres (Cloud) über dieselbe `database_url`.
  - Für neue nullable Spalten/Unique-Constraints an bestehenden Tabellen übernimmt
    `app.db.sync_schema` automatisch ein leichtgewichtiges Nachziehen (Ersatz für Alembic).
- Fachlogik in [`app/services/`](app/services) (Rezeptskalierung/-kosten, Preisermittlung,
  Einkaufsaggregation, Feedback, Validierung, Backup/Restore, Export, Cloud-Sync
  ([`sync_service.py`](app/services/sync_service.py)), Datenbank-Modus-Entscheidung
  ([`database_selection_service.py`](app/services/database_selection_service.py))).
- Nutzerdoku: [`docs/user_guide.md`](docs/user_guide.md).

### Bekannte Grenzen

- Lokaler Standardmodus (SQLite) hat keine echte Mehrbenutzer-Gleichzeitigkeit - dafür den
  Cloud-Modus nutzen.
- Cloud-Sync überträgt keine Löschungen (siehe "Offline arbeiten" oben) und löst nur echte
  Bearbeitungskonflikte auf Zeilenebene auf (ganze Zeile "meine" oder "Cloud", kein
  Feld-für-Feld-Merge).
- Einheiten werden bei der Einkaufsaggregation nicht automatisch umgerechnet.
- `git` ist in manchen Entwicklungsumgebungen hier nicht im `PATH` - direkter Pfad zu
  Git for Windows funktioniert.
