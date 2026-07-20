# Benutzerhandbuch

Dieses Handbuch beschreibt den aktuellen UI-Prototypen (Phase 5). Die Anwendung ersetzt schrittweise die Excel-Arbeitsmappe fuer die Zeltlager-Verpflegungsplanung.

## Erster Start

Beim allerersten Start fragt die App nach einem Speicherort fuer die Datenbankdatei:

1. Ein Hinweisfenster zeigt den vorgeschlagenen Standardpfad (`instance/zeltlager_kueche.sqlite3` im Projektordner).
2. Im folgenden Dateidialog kann dieser Pfad uebernommen oder ein anderer Ort gewaehlt werden.
3. Liegt der gewaehlte Ort auf OneDrive, Dropbox, Google Drive oder einem Netzlaufwerk, warnt die App und fragt vor dem Fortfahren nach Bestaetigung (siehe "SQLite auf Drive-Laufwerken" im README).
4. Der gewaehlte Pfad wird gespeichert (`%APPDATA%\ZelaKueche\settings.json`) und beim naechsten Start automatisch wiederverwendet.

Der Pfad kann spaeter jederzeit unter **Einstellungen** geaendert werden (wirksam nach einem Neustart der App).

## Navigation

Die Seitenleiste links schaltet zwischen den Modulen um:

- **Dashboard** - Kennzahlen und Warnungen fuer das ausgewaehlte Camp-Jahr
- **Jahresplanung** - Camp-Jahre anlegen, Mahlzeiten-Slots generieren und pflegen
- **Rezepte** - Rezepte suchen, anlegen, bearbeiten, Zutaten pflegen, Kosten berechnen
- **Zutaten** - Zutatenstammdaten und Aliasnamen (z. B. Tippfehler-Varianten)
- **Preise** - aktuelle Preise je Zutat und Jahr, fehlende Preise, Uebernahme aus Vorjahr
- **Einkaufsliste** - aus der Jahresplanung generierte Einkaufsliste, Status je Position, CSV-/Excel-Export
- **Feedback** - Rueckmeldungen je Rezept und Jahr, automatische Mengenfaktor-Berechnung
- **Import/Export** - Excel erneut importieren, Rezepte exportieren, Backup/Restore, Datenbankpruefung
- **Einstellungen** - Datenbankpfad, Laufwerkswarnung, Version

## Typischer Ablauf fuer ein neues Camp-Jahr

1. **Jahresplanung**: neues Camp-Jahr mit Zeitraum anlegen, dann "Mahlzeiten-Slots generieren" klicken (legt Fruehstueck/Mittag/Abend fuer jeden Tag an).
2. Je Mahlzeit ein Rezept, Portionenzahl und Zielgruppe eintragen und speichern.
3. **Preise**: fehlende Preise pruefen (rot markiert) und ergaenzen, oder Preise aus dem Vorjahr uebernehmen.
4. **Einkaufsliste**: "Einkaufsliste generieren" klicken - aggregiert alle geplanten (nicht abgesagten) Mahlzeiten zu Einkaufspositionen mit Mengensumme und Kostenschaetzung.
5. Nach dem Lager: **Feedback** je gekochtem Rezept erfassen (Bewertung, gekochte vs. geplante Portionen, Reste, Tipps). Der Mengenfaktor fuer naechstes Mal wird automatisch berechnet.

## Farben und Warnungen

- **Rot**: fehlt/kritisch (z. B. fehlender Preis, Datenbank auf riskantem Laufwerk)
- **Gelb**: pruefen (z. B. offene Einkaeufe)
- **Gruen**: erledigt/ok
- **Blau**: Information/Hinweis

## Backup und Wiederherstellung

Unter **Import/Export**:

- "Backup erstellen" kopiert die aktuelle Datenbank zeitgestempelt nach `backups/`.
- "Aus Backup wiederherstellen" ersetzt die aktuelle Datenbank durch ein ausgewaehltes Backup - erfordert eine Bestaetigung und sichert den aktuellen Stand vorher automatisch zusaetzlich.
- "Datenbank pruefen" fuehrt eine SQLite-Integritaetspruefung aus.

## Bekannte Grenzen des Prototyps

- Keine Mehrbenutzer-Gleichzeitigkeit (SQLite-Grenze, siehe README).
- Einheiten werden bei der Einkaufsaggregation nicht automatisch umgerechnet (z. B. `kg` und `g` bleiben getrennte Positionen).
- Der Datenbankpfad-Wechsel in den Einstellungen erfordert einen Neustart der App.
