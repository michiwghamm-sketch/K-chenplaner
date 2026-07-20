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

- **Dashboard** - Kennzahlen und Warnungen fuer die ausgewaehlte Zeltlagerwoche
- **Wochenplan** - die Zeltlagerwoche als Tabelle: Tage als Spalten, Tagesverantwortlicher und die drei Mahlzeiten als Zeilen
- **Rezepte** - Rezepte suchen, anlegen, bearbeiten, Zutaten pflegen, Kosten berechnen
- **Zutaten** - Zutatenstammdaten und Aliasnamen (z. B. Tippfehler-Varianten)
- **Preise** - aktuelle Preise je Zutat und Jahr, fehlende Preise, Uebernahme aus Vorjahr
- **Einkaufsliste** - aus der Jahresplanung generierte Einkaufsliste, Status je Position, CSV-/Excel-Export
- **Feedback** - Wochenplan einer Zeltlagerwoche durchgehen und je Mahlzeit Rueckmeldung erfassen
- **Import/Export** - Excel erneut importieren, Rezepte exportieren, Backup/Restore, Datenbankpruefung
- **Einstellungen** - Datenbankpfad, Laufwerkswarnung, Version

## Der Wochenplan

Ein Zeltlager dauert typischerweise etwas mehr als eine Woche (z. B. Samstag bis zum uebernaechsten Sonntag). Der Wochenplan bildet genau das ab: pro Tag im Zeitraum eine Spalte, darunter vier Zeilen:

- **Verantwortlich**: wer an diesem Tag fuer die Kueche verantwortlich ist
- **Fruehstueck**, **Mittagessen**, **Abendessen**: das jeweils geplante Rezept (inkl. Portionenzahl in Klammern, sobald gesetzt)

Ein Doppelklick auf ein Feld oeffnet den passenden Dialog:

- Doppelklick auf "Verantwortlich" eines Tages -> Name und Notiz fuer den Tag eintragen
- Doppelklick auf eine Mahlzeit -> Rezept auswaehlen, Portionen, Zielgruppe, Status (geplant/bestellt/gekocht/abgesagt) und Notizen pflegen

Ein rot markiertes Mahlzeit-Feld bedeutet: Rezept ist gesetzt, aber es fehlt noch eine Portionenzahl.

## Typischer Ablauf fuer eine neue Zeltlagerwoche

1. **Wochenplan**: neue Zeltlagerwoche mit Start-/Enddatum anlegen, dann "Wochenplan-Raster anlegen" klicken (legt Fruehstueck/Mittag/Abend fuer jeden Tag im Zeitraum an; einzelne Felder lassen sich aber auch ohne diesen Schritt direkt per Doppelklick befuellen).
2. Je Tag den Verantwortlichen eintragen, je Mahlzeit ein Rezept, Portionenzahl und Zielgruppe.
3. **Preise**: fehlende Preise pruefen (rot markiert) und ergaenzen, oder Preise aus dem Vorjahr uebernehmen.
4. **Einkaufsliste**: "Einkaufsliste generieren" klicken - aggregiert alle geplanten (nicht abgesagten) Mahlzeiten aus dem Wochenplan zu Einkaufspositionen mit Mengensumme und Kostenschaetzung.
5. Nach dem Lager: **Feedback** oeffnen, Camp-Jahr auswaehlen - links erscheint der komplette Wochenplan als Liste (Datum, Mahlzeit, Rezept, Erledigt/Offen). Mahlzeit anklicken, rechts das Feedback erfassen: Wie kam es an (1-5), hat die Menge gereicht (Ja/zu wenig/zu viel), gekochte Portionen, Restmenge, Wiederholen ja/nein, sowie was beim Kochen gut oder schlecht lief. Die geplante Portionenzahl kommt automatisch aus dem Wochenplan, der Mengenfaktor fuer naechstes Mal wird automatisch berechnet.

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
