# VBA-Funktionsabbildung

Diese Datei ordnet die aktuell erkannte VBA-Logik den geplanten Python-Funktionen zu.

## Zielbild

Nicht jede technische Excel-Eigenheit muss unveraendert uebernommen werden. Relevant ist eine fachlich gleichwertige oder bessere Funktion fuer:

- Rezeptverwaltung
- Rezeptauswahl
- Wochen-/Jahresplanung
- Preisverwaltung
- Kalkulation
- Einkaufslistenerstellung

## Erkannte Hauptlogik

### 1. Rezeptuebersicht als Steuerzentrale

VBA-Modul: `VBA/Tabelle1`

Erkannte Prozeduren:

- `Private Sub CommandButton1_Click()`
- `Private Sub CommandButton2_Click()`
- `Private Sub Worksheet_Activate()`
- `Private Sub ScrollBar1_Change()`
- `Private Sub Worksheet_BeforeDoubleClick(ByVal Target As Range, Cancel As Boolean)`
- `Sub UpdateScrollBar()`
- `Sub UpdateRecipeList()`
- `Sub NeuesRezeptHinzufügen()`
- `Sub EinkaufslisteErstellen()`
- `Sub BubbleSort(arr As Variant)`

Fachliche Bedeutung:

- Die Rezeptuebersicht ist aktuell die zentrale Start- und Navigationsseite.
- Es gibt eine scrollbare sichtbare Rezeptliste.
- Rezepte koennen per Interaktion ausgewaehlt werden.
- Ein Doppelklick springt vom Uebersichtsblatt direkt in das jeweilige Rezeptblatt.
- Ein Button legt neue Rezeptblaetter auf Basis der Vorlage an.
- Ein weiterer Button erstellt eine aggregierte Einkaufsliste aus den ausgewaehlten Rezepten.

Python-Folgerung:

- Diese Logik wird spaeter nicht als Tabelleninteraktion, sondern als richtige Rezeptliste mit Detailansicht umgesetzt.
- Die aktuelle Scrollbar-/Checkbox-Mechanik ist ein UI-Workaround fuer Excel und muss nicht 1:1 technisch kopiert werden.
- Die fachlichen Aktionen selbst muessen erhalten bleiben:
  - Rezept anlegen
  - Rezept oeffnen
  - Rezept auswaehlen
  - Einkaufsliste aus Auswahl erzeugen

### 2. Ausgewaehlte Rezepte als Zustand

VBA-Modul: `VBA/Modul1`

Erkannte Prozedur:

- `Sub InitializeSelectedRecipes()`

Fachliche Bedeutung:

- Ausgewaehlte Rezepte werden aktuell in einem `Scripting.Dictionary` gehalten.

Python-Folgerung:

- In der App wird daraus kein globales Makro-Dictionary, sondern sauberer UI-/Service-Zustand.

### 3. Automatische Einkaufsliste aus Rezepten

VBA-Modul: `VBA/Tabelle1`

Fachliche Bedeutung von `EinkaufslisteErstellen()`:

- Ausgewaehlte Rezepte werden durchlaufen.
- Zutaten werden aggregiert.
- Preise werden uebernommen.
- Bei Preisunterschieden wird der hoehere Preis bevorzugt und gemeldet.
- Eine Einkaufsliste wird neu aufgebaut.
- Gesamtkosten und Gerichte werden ausgegeben.

Python-Folgerung:

- Diese Funktion ist Kernlogik und muss fachlich uebernommen werden.
- Die Python-Version sollte das robuster machen:
  - nachvollziehbare Preisquelle
  - explizite Konfliktliste bei abweichenden Preisen
  - bessere Einheitenpruefung
  - persistente Einkaufslisten statt nur neues Blatt

### 4. Neues Rezept aus Vorlage erzeugen

VBA-Modul: `VBA/Tabelle1`

Fachliche Bedeutung von `NeuesRezeptHinzufügen()`:

- Name wird abgefragt.
- Vegetarisch ja/nein wird abgefragt.
- Ein neues Blatt wird aus der Vorlage kopiert.
- Rezeptname wird eingetragen.
- Tabellenblattreiter wird farblich markiert.

Python-Folgerung:

- Fachlich relevant sind:
  - Rezept anlegen
  - Kategorie bzw. vegetarisch-Status setzen
  - Standardstruktur fuer neues Rezept bereitstellen
- Das Kopieren eines ganzen Excel-Blatts ist nur die aktuelle technische Umsetzung und wird in Python durch ein Formular plus Standardwerte ersetzt.

### 5. Preise aus Rezepten in Preisliste uebernehmen

VBA-Modul: `VBA/DieseArbeitsmappe`

Erkannte Prozeduren:

- `Private Sub Workbook_Open()`
- `Private Sub Workbook_SheetChange(ByVal Sh As Object, ByVal Target As Range)`

Fachliche Bedeutung:

- Beim Oeffnen wird der Auswahlzustand initialisiert.
- Aenderungen in Rezeptblaettern koennen neue Zutaten bzw. Preise in die Preisliste nachtragen.

Python-Folgerung:

- Diese Synchronisierung ist fachlich relevant, aber in Python besser als expliziter Speichervorgang bzw. Service-Regel abbildbar.
- Keine impliziten Seiteneffekte ueber Blatt-Events mehr.

### 6. Preislisten-Aenderungen in Rezepte zurueckschreiben

VBA-Modul: `VBA/Tabelle35`

Erkannte Prozedur:

- `Private Sub Worksheet_Change(ByVal Target As Range)`

Fachliche Bedeutung:

- Wenn in der Preisliste ein Preis geaendert wird, werden passende Rezeptzeilen in allen Rezeptblaettern aktualisiert.

Python-Folgerung:

- Das ist fachlich sehr relevant.
- In Python sollte Preisermittlung aber nicht ueber Zellkopien laufen, sondern ueber relationale Preisdaten und berechnete Rezeptkosten.
- Wichtig fuer die Migration ist deshalb:
  - Preis zentral speichern
  - Rezeptkosten bei Anzeige/Neuberechnung ableiten
  - optional Preis-Snapshot pro Jahr speichern

### 7. Preisliste aus Rezepten neu erzeugen

VBA-Modul: `VBA/Modul2`

Erkannte Prozedur:

- `Sub ErstellePreisliste()`

Fachliche Bedeutung:

- Durchlaeuft Rezeptblaetter.
- Liest Zutaten und Preise aus.
- Baut die Preisliste neu auf.

Python-Folgerung:

- Das ist ein Migrationssignal fuer die Datenherkunft:
  - Preise stammen zumindest historisch teilweise aus Rezeptblaettern und nicht nur aus einer sauberen Stammdatenliste.
- Beim Import muessen wir deshalb Preisquellen priorisieren und Konflikte dokumentieren.

### 8. Preise aus zentraler Preisliste in Rezeptblaetter uebertragen

VBA-Modul: `VBA/Modul3`

Erkannte Prozedur:

- `Sub PreiseAusPreislisteInZielblattEintragen()`

Fachliche Bedeutung:

- Das aktive Rezeptblatt bekommt Preise und Einheiten aus der Preisliste.
- Fehlende Zutaten koennen interaktiv neu angelegt werden.

Python-Folgerung:

- Fachlich relevant sind:
  - Zutat nachschlagen
  - Einheit und Preis zuordnen
  - fehlende Stammdaten anlegen
- Das sollte spaeter als kontrollierter Dialog in der App umgesetzt werden.

## Vorlaeufige Priorisierung fuer die Python-App

### Muss fachlich 1:1 oder besser erhalten bleiben

- Rezept anlegen und speichern
- Rezepte durchsuchen und auswaehlen
- Zutaten und Preise zentral pflegen
- Rezeptkosten und Portionskosten berechnen
- Einkaufsliste aus Rezeptauswahl oder Planung aggregieren
- Preisaktualisierungen konsistent in Kalkulationen beruecksichtigen

### Darf technisch anders umgesetzt werden

- Scrollbar im Rezeptblatt
- Checkboxen auf Excel-Zellen
- Doppelklick-Navigation zwischen Blaettern
- Blattfarben fuer vegetarisch/fleisch
- Event-getriebene Zell-Synchronisierung

## Offene Punkte fuer die weitere Analyse

- Welche Tabellenblaetter mit leerem oder kleinem VBA-Code enthalten dennoch fachlich relevante Button-Aktionen?
- Ob die Jahresplanung selbst noch weitere Makrologik besitzt oder aktuell hauptsaechlich ueber Formeln arbeitet.
- Ob ActiveX-Steuerelemente ausserhalb der Rezeptuebersicht noch weitere Nutzerfunktionen ausloesen.
