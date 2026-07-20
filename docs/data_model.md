# Datenmodell

Phase 2 definiert die erste relationale Zielstruktur fuer die Python-Anwendung. Das Modell orientiert sich an der Excel-Struktur und der fachlich relevanten VBA-Logik.

## Leitgedanken

- Zutaten, Preise und Rezepte werden als getrennte Stammdaten modelliert.
- Preislogik wird zentralisiert statt ueber Zellkopien synchronisiert.
- Planungs- und Einkaufslogik bauen auf Rezepten und Camp-Jahren auf.
- Importunsicherheit wird nicht verschwiegen, sondern explizit in `import_runs` und `import_issues` gespeichert.
- Das Modell ist SQLite-tauglich, aber bewusst ohne SQLite-spezifische Fachlogik entworfen.

## Kernobjekte

### Zutaten

- `ingredients`
  - Stammdaten fuer Lebensmittel und Zutaten
  - enthaelt Standardeinheit, Kategorie, Lagerart und Aktiv-Status
- `ingredient_aliases`
  - abweichende Schreibweisen, Tippfehler, Synonyme
- `ingredient_prices`
  - historische oder aktuelle Preise pro Zutat
  - speichert Jahr, Gueltigkeit, Quelle, Laden und Notizen

### Rezepte

- `recipes`
  - Rezeptkopf mit Kategorie, Mahlzeitentyp, Standardportionen, Anleitung und Notizen
- `recipe_components`
  - ein Teilstueck eines Rezepts, z. B. "Koettbullar", "Kartoffelbrei", "Soße"
  - rein organisatorisch: gruppiert `recipe_ingredients` fuer Anzeige, PDF-Export und Kostenaufschluesselung
- `recipe_ingredients`
  - Zuordnung Rezept zu Zutat, optional einem `recipe_component` zugeordnet (`component_id`, nullable)
  - Zutaten ohne Teilstueck (z. B. Altdaten aus dem Excel-Import) erscheinen als "Sonstiges"
  - speichert Menge, Einheit, Reihenfolge und optionale Zutaten
- `recipe_versions`
  - Changelog: ein Schnappschuss der Zutatenmengen vor jeder Mengenaenderung (einzelne Zutat oder
    Faktor-Skalierung ueber `recipe_service.scale_recipe_ingredients`)
  - `ingredients_snapshot` ist ein JSON-Textfeld (Teilstueck/Zutat/Menge/Einheit), damit die Historie
    unabhaengig von spaeteren Umbenennungen/Loeschungen bleibt
  - `version_number` zaehlt je Rezept hoch (`UniqueConstraint(recipe_id, version_number)`)

### Lagerjahr und Wochenplan

- `camp_years`
  - eine Zeltlagerwoche (ein "Lagerjahr") mit Zeitraum, Ort und Teilnehmerzahlen
- `camp_days`
  - ein Tag innerhalb der Zeltlagerwoche, primaer fuer den Tagesverantwortlichen (`responsible_person`)
  - ein Eintrag je Datum und Camp-Jahr (`UniqueConstraint(camp_year_id, day_date)`)
- `meal_plan_entries`
  - konkrete geplante Mahlzeiten eines Lagerjahres (bis zu drei je Tag: Fruehstueck/Mittagessen/Abendessen)
  - verknuepft Datum, Mahlzeitentyp, Rezept, Portionen und Einkaufsinformationen

### Feedback

- `recipe_feedback`
  - Rueckmeldung je konkreter Mahlzeit im Wochenplan (`meal_plan_entry_id`, `unique`) - dadurch kann dasselbe
    Rezept an zwei Tagen der Woche stehen und bekommt trotzdem je Mahlzeit ein eigenes Feedback
  - `meal_plan_entry_id` ist nullable, da aus Excel importiertes Alt-Feedback keiner konkreten Mahlzeit
    zugeordnet werden kann (dort bleibt nur der camp_year_id/recipe_id-Bezug)
  - Bewertung ("wie kam es an?"), `quantity_sufficient` ("hat die Menge gereicht? Ja/Zu wenig/Zu viel"),
    Wiederholungswunsch, geplante/gekochte Portionen, Restmenge und qualitative Erfahrungswerte
    (Ablauf-Tipps, was lief gut, was aendern)

### Einkauf

- `shopping_lists`
  - benannte Einkaufslisten pro Lagerjahr
- `shopping_list_items`
  - aggregierte Einkaufspositionen mit Menge, Preis, Status, Einkaufsdatum und Rezeptbezug

### Anwendung und Import

- `app_settings`
  - einfache Key/Value-Konfiguration
- `import_runs`
  - Dokumentation einzelner Excel-Importe
- `import_issues`
  - offene oder geloeste Importprobleme auf Blatt-/Zellebene

## Wichtige Beziehungen

- Eine `ingredient` kann mehrere `ingredient_aliases` und `ingredient_prices` haben.
- Ein `recipe` hat viele `recipe_components`, `recipe_ingredients` und `recipe_versions`.
- Ein `recipe_component` hat viele `recipe_ingredients` (optional - `component_id` ist nullable).
- Ein `camp_year` hat viele `camp_days`, `meal_plan_entries`, `recipe_feedback`-Eintraege und `shopping_lists`.
- Eine `shopping_list` hat viele `shopping_list_items`.
- Ein `import_run` hat viele `import_issues`.

## Fachliche Abbildung aus Excel und VBA

### Preislogik

In Excel werden Preise teilweise aus Rezeptblaettern gesammelt und teilweise aus der Preisliste zurueck in Rezepte geschrieben. In der Datenbank gilt stattdessen:

- Preise leben primaer in `ingredient_prices`
- Rezepte referenzieren Zutaten, nicht kopierte Preiszellen
- Kosten werden spaeter in Services berechnet

### Rezeptauswahl und Einkaufsliste

Die VBA-Logik aggregiert ausgewaehlte Rezepte in eine Einkaufsliste. In der Python-App wird diese Auswahl spaeter ueber Planung oder direkte Mehrfachauswahl abgebildet. Die persistente Zielstruktur dafuer sind:

- `meal_plan_entries`
- `shopping_lists`
- `shopping_list_items`

### Feedback

Die Excel-Datei enthaelt bereits Feedback mit Bewertungs- und Erfahrungsdaten. Das wird direkt in `recipe_feedback` uebernommen.

## Offene Modellfragen aus Phase 3 - Entscheidung nach Phase 4

- **Eigene Tabellen fuer `units`/`stores`/`recipe_categories`?** Vorerst nein. Kategorie, Mahlzeitentyp und Einheit bleiben freie Textfelder (mit Normalisierung ueber `app/utils/units.py` und `app/utils/normalization.py`). Die Datenmengen sind klein genug, dass eine Freitext-Pflege mit Vorschlagslisten in der UI reicht. Falls spaeter eine feste Kategorienliste gewuenscht ist, laesst sich das nachtraeglich ergaenzen, ohne bestehende Daten zu verlieren.
- **`linked_recipes_text` vs. Normalisierung?** Bleibt vorerst ein Textfeld. `shopping_service.generate_shopping_list()` befuellt es beim Generieren automatisch mit den Namen aller Rezepte, die zu einer aggregierten Position beigetragen haben. Eine Join-Tabelle waere nur noetig, wenn einzelne Einkaufspositionen spaeter wieder auf einzelne Mahlzeiten zurueckgefuehrt werden muessten.
- **Einheitenumrechnung?** Nicht automatisiert. `shopping_service` aggregiert Mengen nur, wenn Zutat *und* Einheit exakt uebereinstimmen (z. B. `kg` wird nicht mit `g` zusammengefuehrt). Das vermeidet stille Rechenfehler, erfordert aber gepflegte, konsistente Einheiten je Zutat.

## Phase 4: Fachlogik-Services

Die Services unter `app/services/` kapseln alle Berechnungen und Validierungen, die vorher in Excel-Formeln/VBA steckten:

| Service | Kernfunktionen |
| --- | --- |
| `price_service` | `find_best_price` (Jahrestreffer, sonst neuester Preis), `missing_price_ingredients`, `copy_prices_from_year`, `compare_years` |
| `recipe_service` | `scale_recipe` (Mengen auf Zielportionen skalieren), `calculate_recipe_cost` (Gesamt-/Portionskosten inkl. Kosten je Zutatenzeile), Teilstueck-CRUD (`create_component`/`update_component`/`delete_component`), Changelog (`create_version_snapshot`/`list_versions`/`parse_version_snapshot`), `scale_recipe_ingredients`/`update_ingredient_quantity` (versionieren automatisch vor jeder Mengenaenderung), `suggested_scale_factor` (letzter Feedback-Faktor) |
| `ingredient_service` | Suche, CRUD, Alias-Verwaltung |
| `planning_service` | Zeltlagerwoche anlegen, `generate_daily_meal_slots` legt pro Tag `camp_days` + bis zu drei `meal_plan_entries` an (idempotent), `get_or_create_camp_day`/`get_or_create_meal_entry` fuer die Einzelfeld-Bearbeitung im Wochenplan-Raster, `set_day_responsible`, Status-Uebergaenge, Einkaufstag-Herleitung |
| `shopping_service` | `generate_shopping_list` aggregiert alle geplanten (nicht abgesagten) `meal_plan_entries` eines Camp-Jahrs zu Einkaufspositionen - liest also direkt aus dem Wochenplan |
| `feedback_service` | `list_feedback_candidates` listet alle Mahlzeiten eines Camp-Jahrs mit Rezept auf; `save_meal_feedback`/`get_or_create_meal_feedback` verwalten das Feedback je Mahlzeit-Slot; `calculate_quantity_factor` = gekochte / geplante Portionen |
| `validation_service` | fehlende Preise/Einheiten, Rezepte ohne Zutaten, Planung ohne Portionen, 0-Preis-Positionen, moegliche Zutaten-Dubletten (Aehnlichkeitsvergleich via `difflib`) |
| `backup_service` | zeitgestempeltes Backup, Restore nur mit expliziter Bestaetigung, SQLite-Integritaetspruefung |
| `import_service` / `export_service` | UI-Wrapper fuer den Excel-Import bzw. CSV/Excel/PDF-Export; `export_recipe_to_pdf` erzeugt eine nach Teilstuecken gegliederte, Kolping-gebrandete Rezeptkarte (reportlab) mit Logo aus `app/assets/kolping_logo.jpeg` |

Alle Services sind reine Python-Funktionen ohne UI-Abhaengigkeit und werden in `tests/` mit pytest abgedeckt.

### Wochenplan als zentrale Planungsquelle

Der Wochenplan (`camp_days` + `meal_plan_entries` eines `camp_year`) ist die einzige Quelle fuer:

- **Einkaufsliste**: `shopping_service.generate_shopping_list` liest ausschliesslich die `meal_plan_entries` des gewaehlten Camp-Jahrs.
- **Feedback**: Die Feedback-Ansicht zeigt je Camp-Jahr direkt die Liste der geplanten Mahlzeiten (aus `meal_plan_entries`) mit Erledigt/Offen-Status; jede Rueckmeldung haengt an genau einer Mahlzeit und uebernimmt deren geplante Portionenzahl automatisch.
- **Dashboard**: Kennzahlen (geplante Mahlzeiten/Portionen/Budget, fehlende Preise) werden direkt aus dem Wochenplan berechnet.

Wird im Wochenplan ein Rezept geaendert, wirkt sich das also automatisch auf Einkaufsliste, Dashboard und den Feedback-Vorschlag aus - eine manuelle Synchronisation ist nicht noetig.
