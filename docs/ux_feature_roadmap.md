# UX-Überarbeitung + Feature-Erweiterungen (Roadmap)

Dieses Dokument ist der lebende Fortschritts- und Umsetzungsplan für eine vollständige
UX-Durchsicht der App plus die daraus und aus Nutzergesprächen entstandenen Feature-Wünsche.
Es liegt im Repo (statt nur lokal), damit der Stand über mehrere Sitzungen und auch für andere
gleichzeitig am Repo arbeitende Agents sichtbar bleibt.

## Status (Stand 2026-08-01, Pause nach Fix 15 - Teil 1 komplett)

**Erledigt und einzeln auf `master` committet** (jeweils mit Smoke-Test + voller Testsuite
grün geprüft):

| # | Commit | Inhalt |
|---|---|---|
| 1 | `faa2ef7` | Toter Open-Prices-Massenimport-Code entfernt |
| 2 | `9370dcc` | Dirty-Check gegen Datenverlust beim Rezeptwechsel/Abbrechen |
| 3 | `254dee8` | Feedback-Bewertung startet nicht mehr bei "1 Stern" |
| 4 | `d9ca074` | "Nach Geschmack"-Zutaten (Menge 0) korrekt anlegbar/bearbeitbar |
| 5 | `095a451` | "Speichern & nächste Zutat" beim Zutaten-Erfassen |
| 6 | `1d14292` | Rezept-Skalierung per Zielportionen statt nur Faktor |
| 7 | `c2e383d` | Kostenrechner-Vorbelegung mit Camp-Teilnehmerzahl + Stale-Hinweis |
| 8 | `894d3dc` | "Nächstes offenes Feedback" automatisch anspringen |
| 9 | `dcec968` | Händler-Autovervollständigung in der Einkaufsliste |
| 10 | `7bfc6f9` | "Löschen"-Buttons app-weit visuell von Sekundäraktionen abgehoben (role="danger") |
| 11 | `dc10558` | Teilstücke im Rezept per ▲/▼ sortierbar |
| 12 | `25f5152` | Fehlende-Preise-Banner klickbar (springt zur Zutat) |
| 13 | `16cdf65` | Bestätigung vor "Barcode-Verknüpfung entfernen" |
| 14 | `35b202b` | Verbindungstest vor dem Speichern einer Cloud-Verbindung |
| 15 | `37cb1b9` | Wochenplan: "Kompakte Ansicht"-Checkbox gegen horizontales Scrollen |

**Damit ist Teil 1 (UX-Verbesserungen an der bestehenden App, Tier 1-3) vollständig
abgeschlossen.**

**Noch offen:**

- Teil 2 komplett (F1-F6): Wochenplan aus Vorjahr, Grundausstattungsliste, Kategorie-Gruppierung
  Einkaufsliste, Vorrats-Flag, Abrechnungsmodul (F6a Desktop + F6b Mobil).
- Hinweis: parallel zu dieser Session hat ein anderer Agent eine "Einkaufstrips planen"-Funktion
  (Teilmengen der Einkaufsliste auf Personen verteilen) in `shopping_view.py`/
  `shopping_service.py`/`mobile_web/` ergänzt und nach `master` gemergt (Commits bis `f12033f`).
  F2 (manuelle Position in der Einkaufsliste) und F4 (Kategorie-Gruppierung) sollten vor
  Umsetzung kurz gegen den aktuellen Stand von `shopping_view.py` geprüft werden, da sich
  Tabellenspalten (`SHOPPING_TABLE_COLUMNS`) und Gruppierungsmodi (`GROUP_MODES`) inzwischen
  verändert haben.

**Arbeitsweise-Hinweis für die Fortsetzung:** Wird gleichzeitig ein anderer Agent im
Hauptarbeitsverzeichnis aktiv (anderer Branch, uncommitted WIP), erst per `git status`/
`git branch -a`/`git log` prüfen, bevor im Hauptverzeichnis committet wird - im Zweifel einen
eigenen `git worktree add <pfad> master` für die eigene Arbeit anlegen und dort committen, um
Commits nicht versehentlich auf dem Branch des anderen Agents landen zu lassen.

---

## Kontext

ZelaKüche ist eine PySide6-Desktop-App (+ schlanke Flask-Mobile-Web-Ansicht), die ein
3-köpfiges ehrenamtliches Küchenteam bei der Verpflegungsplanung eines einwöchigen
Zeltlagers (~75 Kinder, ~25 Betreuer) unterstützt. Die Fachlogik (Rezeptskalierung,
Kostenberechnung, Einkaufsaggregation, Feedback-Rückkopplung) ist bereits sehr ausgereift.

Dieser Plan entstand aus einer vollständigen Durchsicht aller UI-Module
(`app/ui/*.py`, ~7000 Zeilen) plus der zugehörigen Services. Ziel laut Nutzer: zuerst die
**bestehende Bedienung** kritisch durchgehen und verbessern ("macht alles so Sinn wie es
implementiert ist?"), danach die bereits besprochenen **neuen Features** einplanen, und für
beides eine sinnvolle Umsetzungsreihenfolge.

Zwei Erkenntnisse aus der Durchsicht sind besonders wichtig für die Priorisierung:

- Es gibt einen **echten Bug mit Datenverlust-Potenzial** (unbestätigter Rezeptwechsel wirft
  ungespeicherte Änderungen weg). Das wiegt schwerer als Komfort-Verbesserungen und kommt
  daher zuerst.
- Der Open-Prices-Massenimport (`_auto_import_open_prices`/`_import_open_prices` in
  `ingredients_view.py`) ist zwar implementiert, aber nie an einen Button angeschlossen -
  laut Rückmeldung lohnt sich ein Reparieren/Freischalten nicht, da die Open-Prices-Anbindung
  insgesamt hakelig ist (Produktvorschau lädt schlecht, Trefferquote mäßig). Statt den toten
  Pfad ans Netz zu bringen, wird er ersatzlos entfernt (siehe Tier 1). Eine grundlegende
  Überarbeitung der Open-Prices-Anbindung selbst ist NICHT Teil dieses Plans.
- Die bereits besprochene Abrechnungs-Funktion (Teil 2, F6) soll laut Rückmeldung **möglichst
  nah am offiziellen Kolpingjugend-Formular** ausgeben und **auch mobil während des Lagers**
  nutzbar sein - das ist der mit Abstand größte Einzelposten und wird deshalb als eigene,
  zweigeteilte Phase ganz ans Ende gestellt.

---

## Teil 1: UX-Verbesserungen an der bestehenden App

### Tier 1 – Bugfixes / Datenintegrität (höchste Priorität)

1. **Toten Open-Prices-Massenimport-Code entfernen**
   `app/ui/ingredients_view.py`: `_auto_import_open_prices` und `_import_open_prices` waren an
   keinen Button angeschlossen und wären bei Aufruf ohnehin sofort gecrasht (referenzierten
   `self.price_status_label`/`self.price_import_log`, die in `_build_ui` nie erzeugt wurden).
   Da die Open-Prices-Trefferquote laut Rückmeldung ohnehin mäßig ist und die Produktvorschau
   schlecht lädt, lohnt sich ein Reparieren nicht - stattdessen wurden beide Methoden und alle
   ausschließlich von ihnen genutzten Hilfsfunktionen/Importe entfernt. Der bereits
   funktionierende Einzel-Zutat-Weg (`_search_open_prices_product`, verbunden mit
   `search_barcode_button`) bleibt unangetastet.

2. **Ungespeicherte Rezept-Änderungen nicht mehr stillschweigend verwerfen**
   `app/ui/recipes_view.py`: `_on_recipe_selected`/der "Abbrechen"-Button luden beim
   Wechsel/Abbrechen sofort neu, ohne zu prüfen, ob Formularfelder (Name, Notizen, Portionen)
   gegenüber dem geladenen Stand verändert wurden. Fix: Dirty-Flag, das bei jeder Feldänderung
   gesetzt und bei Laden/Speichern zurückgesetzt wird; vor Wechsel/Abbrechen bei gesetztem Flag
   `confirm_dialog` einblenden.

3. **Feedback-Bewertung nicht mit "1 Stern" vorbelegen**
   `app/ui/feedback_view.py`: `rating_spin` startete ohne vorhandenes Feedback bei `1`
   (schlechteste Bewertung) - ein Fehlklick auf "Speichern" ohne bewusste Bewertung erzeugte
   damit ungewollt ein "kam gar nicht an"-Feedback. Spinbox hat jetzt einen expliziten
   "Nicht bewertet"-Zustand (0), der beim Speichern auf `rating=None` gemappt wird.

4. **"Nach Geschmack"-Zutaten (Menge 0, optional) nicht mehr kaputt bearbeitbar**
   `app/ui/dialogs.py` (`AddRecipeIngredientDialog`): `quantity_spin.setRange(0.001, ...)`
   klemmte beim Öffnen einer bestehenden Menge-0-Zutat den Wert unsichtbar auf 0.001. Neue
   Checkbox "nach Geschmack (ohne feste Menge)" deaktiviert die Mengen-Eingabe und liefert
   `quantity=0`/`optional=True`, unabhängig vom zuletzt angezeigten Spinbox-Wert.

### Tier 2 – Effizienz für den Alltag unter Zeitdruck

5. **Rezept-Zutaten schneller erfassen**
   `AddRecipeIngredientDialog` hat beim Neuanlegen jetzt einen Button "Speichern & nächste
   Zutat", der speichert und direkt einen neuen leeren Dialog für dieselbe Position öffnet,
   statt jedes Mal zur Rezeptansicht zurückzuspringen.

6. **Skalierung per Zielportionen statt nur Faktor**
   `ScaleRecipeDialog` hat bei bekannter Standardportionenzahl des Rezepts jetzt zusätzlich ein
   Zielportionen-Feld, bidirektional mit dem Faktor-Feld gekoppelt.

7. **Kostenrechner mit Camp-Kontext vorbelegen**
   `cost_portions_spin` fällt ohne eigene Standardportionenzahl des Rezepts jetzt auf die
   Teilnehmerzahl des aktuell gewählten Zeltlagers zurück (statt der willkürlichen Zahl 10).
   Zusätzlich markiert ein Hinweis ("⚠ ... bitte neu berechnen") die Kostenanzeige als veraltet,
   wenn Portionen/Preisjahr nach einer Berechnung geändert wurden.

8. **"Nächstes offenes Feedback" nach dem Speichern**
   `feedback_view.py` springt nach dem Speichern automatisch zur nächsten Zeile mit Status
   "Offen" (umlaufend), statt auf dem gerade gespeicherten Rezept stehen zu bleiben.

9. **Händler mit Autovervollständigung statt Freitext**
   Das Händler-Feld je Einkaufsposition ist jetzt eine editierbare `QComboBox`, deren
   Vorschlagsliste aus `shopping_service.list_known_stores()` (alle bisher vergebenen
   Händlernamen) gespeist wird.

### Tier 3 – Konsistenz & Klarheit

10. **Löschen visuell von Deaktivieren abheben** ✅ - alle "Löschen"-Buttons app-weit (Rezept,
    Zutat, Preis, Feedback, Einkaufsliste, Einheit) haben jetzt `role="danger"` (rot) statt
    `role="secondary"` (orange, wie harmlose Aktionen).
11. **Teilstücke sortierbar machen** ✅ - `recipe_service.move_component()` (analog zu
    `move_step()`) plus ▲/▼-Buttons je Teilstück-Band.
12. **Fehlende-Preise-Banner klickbar machen** ✅ - Namen im Banner sind jetzt Links
    (`missing_prices_label` als RichText), Klick springt direkt zur Zutat.
13. **Bestätigung vor "Barcode-Verknüpfung entfernen"** ✅ - `confirm_dialog` ergänzt, konsistent
    mit allen anderen destruktiven Aktionen in derselben Ansicht.
14. **Verbindungstest vor dem Speichern einer Cloud-Verbindung** ✅ - `_connect_cloud_database`
    testet jetzt mit `check_connectivity` (gleiches Muster wie `_sync_now`), bevor gespeichert wird.
15. **Wochenplan kompakter/übersichtlicher** ✅ - neue "Kompakte Ansicht"-Checkbox schaltet
    Tagesspalten von 210px auf 130px um.

*Bewusst zurückgestellt (aus vorheriger Analyse als geringe Priorität bestätigt bzw. rein
intern ohne Nutzerimpact):* Stale-Einkaufsliste-Warnung nach Plan-Änderung (Planänderungen
sind laut Rückmeldung selten), Zusammenführen der Farbkonstanten aus `widgets.py`/`theme.py`.

---

## Teil 2: Neue Features

Reihenfolge nach Aufwand/Nutzen (kleinste, klar umrissene Verbesserung zuerst):

### F1. Wochenplan aus Vorjahr übernehmen

Neue Funktion `planning_service.copy_camp_year_plan(session, source_camp_year, target_camp_year,
*, scale_portions=False)`: kopiert `camp_days`/`meal_plan_entries` **positionsbasiert nach
Tag-Index innerhalb der Lagerwoche** (Tag 1 → Tag 1 usw., nicht nach Wochentag-Name, da sich
die echten Kalendertage jährlich verschieben). Kopiert Rezept, `target_group`, `diet_scope`,
optional `notes`; **füllt nur leere Slots** (idempotent wie das bestehende
`generate_daily_meal_slots`, überschreibt nie bereits geplante Mahlzeiten im Zieljahr). Mit
`scale_portions=True` werden `planned_portions` mit dem Verhältnis
`participant_count_total(Ziel) / participant_count_total(Quelle)` skaliert (nur anwendbar,
wenn beide Jahre eine Teilnehmerzahl hinterlegt haben).

UI: neuer Button "Wochenplan aus Vorjahr übernehmen" in `planning_view.py` neben "Wochenplan-
Raster anlegen" → Dialog mit Auswahl des Quelljahrs (nur Jahre mit vorhandenem Plan, via
`planning_service.meal_plan_completeness`) und Checkbox zur Portionsskalierung.

### F2. Grundausstattungs-/Non-Food-Liste + manuelle Position

Baut auf der bestehenden `Ingredient`-Tabelle auf statt eines Parallel-Datenmodells:

- `Ingredient` bekommt ein neues nullable Feld `category` (String, Freitext mit
  Vorschlagsliste aus bereits verwendeten Werten - konsistent mit der bestehenden
  Projektentscheidung in `docs/data_model.md`, Kategorien als freies Textfeld statt starrer
  Tabelle zu führen). Schema-Änderung läuft über das vorhandene `app.db.sync_schema`
  (README: "für neue nullable Spalten... übernimmt sync_schema automatisch ein
  leichtgewichtiges Nachziehen").
- Neue schlanke Tabelle `standard_shopping_items` (ingredient_id, default_quantity,
  default_unit, active) als Vorlage für wiederkehrende Positionen (Spülmittel, Müllsäcke,
  Kaffee fürs Team, ...).
- `shopping_service.generate_shopping_list` bekommt einen Parameter, der die aktiven
  Standard-Positionen zusätzlich zu den rezeptbasierten Positionen in die neue Liste
  übernimmt (ohne Rezeptbezug, `linked_recipes_text` bleibt leer).
- UI: kleine Verwaltungsseite für die Standardliste (in `ingredients_view.py` als Abschnitt
  oder eigener Tab) sowie ein "Position manuell hinzufügen"-Button in `shopping_view.py`, der
  eine bestehende Zutat plus frei eingegebener Menge/Einheit/Händler direkt in die aktuelle
  Liste einfügt (nutzt dieselbe `ShoppingListItem`-Struktur, `ingredient_id` ist bereits
  nullable-kompatibel für Sonderfälle).

### F3. Händler-Autovervollständigung
Bereits in Teil 1, Tier 2, Punkt 9 umgesetzt - keine separate Umsetzung nötig.

### F4. Kategorie-Gruppierung der Einkaufsliste

Nutzt das in F2 eingeführte `Ingredient.category`-Feld:

- `shopping_service.group_by_category` analog zu `group_by_store`/`group_by_shopping_day`.
- Gruppierungs-Dropdown in `shopping_view.py` (`GROUP_MODES`) um "Nach Kategorie" erweitern.
- `export_service.export_shopping_list_to_pdf` (`group_by`-Parameter existiert bereits für
  "store"/"day") um `"category"` erweitern.

### F5. Einfache, wartungsarme Vorratserfassung

Da aktuell **nichts** digital erfasst wird (Rückmeldung: "gar nicht digital"), bewusst *kein*
Mengen-Inventar mit Bestandsführung (das würde ohne tatsächliche Zählungen falsche Sicherheit
vortäuschen). Stattdessen:

- `Ingredient` bekommt ein Boolean-Flag `usually_in_stock` (nullable, Default false).
- Bei der Einkaufslisten-Anzeige (nicht bei der Mengenberechnung!) werden Positionen mit
  gesetztem Flag mit einem Hinweis-Icon "vermutlich vorrätig - bitte im Lager prüfen"
  markiert, die Menge wird **nicht** automatisch reduziert. Das vermeidet stille Fehlkalkulation,
  falls der Vorrat doch aufgebraucht ist, gibt dem Team aber einen schnellen Check-Hinweis.

### F6. Bargeld-Abrechnungsmodul (größter Posten, zweigeteilt)

Bildet den Kolpingjugend-DV-Regensburg-Prozess ab (aus `Abgabe Rechnungen 2025.xlsx`
analysiert): nummerierte Belege mit Käufer/Betrag/Kategorie, getrennt in normale Ausgaben /
Tankbelege / Direktrechnungen ans Büro, plus Einnahmen, Anfangsgeldbestand und daraus
berechnetes Restgeld.

**Datenmodell** (neue Tabellen, per `sync_schema` nachziehbar):
- `purchase_receipts`: `camp_year_id`, `receipt_number` (fortlaufend je Camp-Jahr, entspricht
  der Folien-Nummerierung), `purchase_date`, `store`, `amount`, `buyer_name`,
  `category` (`normal` / `tankbeleg` / `direktrechnung`), `notes`.
- `camp_income_entries`: `camp_year_id`, `description`, `amount` (z. B. "Kinder", "Getränkeverkauf").
- `CampYear` bekommt zwei neue nullable Felder: `opening_cash_balance` (Anfangsgeldbestand),
  `notes_settlement` (Freitext für Bürokommunikation).
- Neuer Service `accounting_service.py`: Summenbildung je Kategorie, Formel
  `opening_cash_balance + Σ Einnahmen − Σ Ausgaben(normal) − Σ Ausgaben(tankbeleg) = Restgeld`
  (direktrechnungen fließen NICHT in die Bar-Restgeld-Rechnung ein, genau wie im Original-
  Formular, wo sie separat in einer eigenen Folie landen).

**Phase F6a – Desktop (Erfassung + Auswertung + Export):**
- Neue Ansicht "Abrechnung" (`app/ui/accounting_view.py`), Eintrag in `NAV_ITEMS`/`VIEW_CLASSES`
  (`app/ui/app.py`) analog zu den bestehenden Modulen.
- Tabelle für Belege (Hinzufügen/Bearbeiten/Löschen einer Zeile = ein Beleg), Tabelle für
  Einnahmen, Zusammenfassungsbereich, der die Restgeld-Formel live nachrechnet - Layout und
  Rechenlogik bewusst 1:1 an der "Bargeld-Abrechnung"-Tabelle der Excel-Vorlage orientiert.
- PDF/Excel-Export, der Struktur und Beschriftung der Vorlage nachbildet (Ausgaben-Spalte,
  Einnahmen-Spalte, Tankbelege separat, Gesamt-Abrechnung-Block) - nutzt dieselbe
  `reportlab`/`openpyxl`-Basis wie die bestehenden Exporte in `export_service.py`.
- **Vor Umsetzung dieser Teilphase:** kurzer Abgleich der exakten Spalten/Rundungsregeln
  anhand der Vorlage nötig (z. B. ob Belegnummern beim Löschen einer Zeile neu durchnummeriert
  werden, oder wie im Original Lücken lassen).

**Phase F6b – Mobile Erfassung (`mobile_web/`):**
- Neue Route + Template in `mobile_web/server.py`/`mobile_web/templates/`, PIN-geschützt wie
  die bestehende Einkaufslisten-Ansicht (kein neues Datenmodell, direkter Zugriff über
  `app.models`/`app.db` wie beim Rest von `mobile_web`).
- Einfaches Formular: Betrag, Laden, Käufer (Vorbelegung z. B. aus zuletzt genutztem Namen im
  Browser/lokalem Storage), Kategorie - schreibt direkt einen `purchase_receipts`-Eintrag.
  Bewusst kein Foto-Upload/Beleg-Scan in v1 (deutlich größerer Aufwand, physischer Beleg bleibt
  ohnehin Pflicht fürs Büro) - die App unterstützt nur das laufende Erfassen der Zahlen.

---

## Gesamt-Reihenfolge

Jede Phase ist für sich lauffähig/testbar und baut nicht zwingend auf einer späteren Phase auf
(außer explizit vermerkt):

| Phase | Inhalt | Abhängigkeit | Status |
|---|---|---|---|
| A | Teil 1, Tier 1 (Punkte 1-4: Bugfixes) | - | ✅ erledigt |
| B | Teil 1, Tier 2 (Punkte 5-9: Effizienz) | - | ✅ erledigt |
| C | Teil 1, Tier 3 (Punkte 10-15: Konsistenz) | - | ✅ erledigt |
| D | F1 – Wochenplan aus Vorjahr | - | offen |
| E | F2 – Grundausstattungsliste + manuelle Position | nutzt Autocomplete aus B.9 | offen |
| F | F4 – Kategorie-Gruppierung Einkaufsliste | nutzt `Ingredient.category` aus E | offen |
| G | F5 – Vorrats-Flag | - | offen |
| H | F6a – Abrechnung Desktop | eigenes Datenmodell | offen |
| I | F6b – Abrechnung mobil | baut auf F6a-Datenmodell auf | offen |

Teil 1 (A-C) ist komplett. Weiter mit D (schnell spürbarer Nutzen fürs Team), E+F zusammen
(teilen sich das `category`-Feld), G als kleiner Abschluss, H+I als eigener, größerer Block am
Ende mit kurzer Abstimmung vor F6a-Start.

## Verifikation

- Bestehende Testsuite nach jeder Phase: `.venv\Scripts\python.exe -m pytest` (Services sind
  gut abgedeckt, siehe `tests/`) - neue Service-Funktionen (F1 `copy_camp_year_plan`, F6
  `accounting_service`) bekommen jeweils eigene Tests nach demselben Muster wie
  `tests/test_planning_service.py`/`tests/test_shopping_aggregation.py`.
- Manuelles Durchklicken je Phase über `start_app.bat` bzw. `.venv\Scripts\python.exe
  app\main.py`.
- Für F6b zusätzlich lokaler Mobile-Web-Test: `flask run --port 5055` wie im README
  beschrieben.
