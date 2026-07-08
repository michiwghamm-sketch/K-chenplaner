# Technical Notes

## Phase 1 Vorgehen

Die aktuelle Umgebung stellte weder `python` noch `git` direkt im `PATH` bereit. Fuer die Analyse der bestehenden `.xlsm`-Datei wurde deshalb die OOXML-Struktur direkt gelesen:

- `xl/workbook.xml` fuer Blattliste
- `xl/_rels/workbook.xml.rels` fuer Blatt-Mapping
- `xl/sharedStrings.xml` fuer Textinhalte
- `xl/worksheets/*.xml` fuer Tabellenstrukturen, Header und Formeln

## Konsequenz

Die in `docs/migration_report.md` und `docs/import_mapping.md` dokumentierten Ergebnisse basieren auf einer echten Dateianalyse, aber nicht auf einer ausgefuehrten Python-Laufzeit in dieser Umgebung.

