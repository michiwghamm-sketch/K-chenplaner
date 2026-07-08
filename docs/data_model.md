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
- `recipe_ingredients`
  - Zuordnung Rezept zu Zutat
  - speichert Menge, Einheit, Reihenfolge und optionale Zutaten

### Lagerjahr und Planung

- `camp_years`
  - ein Lagerjahr mit Zeitraum, Ort und Teilnehmerzahlen
- `meal_plan_entries`
  - konkrete geplante Mahlzeiten eines Lagerjahres
  - verknuepft Datum, Mahlzeitentyp, Rezept, Portionen und Einkaufsinformationen

### Feedback

- `recipe_feedback`
  - Rueckmeldungen pro Rezept und Lagerjahr
  - Bewertung, Wiederholungswunsch, Abweichungen bei Portionen und qualitative Erfahrungswerte

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
- Ein `recipe` hat viele `recipe_ingredients`.
- Ein `camp_year` hat viele `meal_plan_entries`, `recipe_feedback`-Eintraege und `shopping_lists`.
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

## Offene Modellfragen fuer Phase 3

- Brauchen wir eigene Stammdatentabellen fuer `units`, `stores` und `recipe_categories`?
- Reicht `linked_recipes_text` in `shopping_list_items` oder brauchen wir spaeter eine Normalisierung ueber Join-Tabellen?
- Welche Einheiten muessen fachlich umgerechnet werden und welche duerfen nicht automatisch aggregiert werden?
