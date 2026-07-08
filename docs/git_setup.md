# Git Setup auf Windows

In der aktuellen Umgebung war `git` nicht im `PATH` verfuegbar. Git for Windows scheint aber lokal installiert zu sein und kann dann auch direkt ueber den Pfad aufgerufen werden:

```powershell
& 'C:\Program Files\Git\cmd\git.exe' --version
```

## Git installieren

1. Git for Windows herunterladen: <https://git-scm.com/download/win>
2. Installer ausfuehren.
3. Standardoptionen beibehalten.
4. Terminal neu oeffnen.
5. Installation pruefen:

```powershell
git --version
```

## Repository im Projektordner initialisieren

1. Terminal im Projektordner oeffnen.
2. Repository initialisieren:

```powershell
git init
git status
```

3. Pruefen, dass die `.gitignore` vorhanden ist.
4. Dateien fuer den ersten Commit vormerken:

```powershell
git add .
git commit -m "Initial project structure and Excel inspection tooling"
```

## Wichtige Hinweise

- Keine SQLite-Dateien committen.
- Keine `.env`-Dateien committen.
- Keine Backups committen.
- Keine personenbezogenen Daten committen.
- Excel-Dateien nur nach ausdruecklicher Freigabe committen.
- Die aktuelle `.gitignore` ignoriert Excel-Dateien bewusst standardmaessig.
