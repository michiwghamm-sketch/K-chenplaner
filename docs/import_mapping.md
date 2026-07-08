# Import Mapping

Vorschlag fuer die erste relationale Zuordnung aus der Excel-Struktur.

## ingredients
- Blatt `Preisliste 2024` mit Confidence `10` und Header-Indizien `[['Zutat', 'Preis', 'Einheit'], ['Apfel', '3.95', '€/kg']]`
- Blatt `Preisliste` mit Confidence `18` und Header-Indizien `[['Zutat', 'Preis', 'Einheit', 'Status', 'Quelle / Shop', 'Stand', 'Preisnotiz'], ['Apfel', '1.59', '€/kg', 'OK']]`
- Blatt `Preisquellen & Pflege` mit Confidence `16` und Header-Indizien `[['Quelle', 'Was liefert sie?', 'Eignet sich für', 'Grenze', 'Aktualisierung', 'Nutzung im Workbook', 'Link/Verweis', 'Status'], ['Destatis / GENESIS Verbraucherpreisindex', 'Index- und Veränderungsraten für Lebensmittelgruppen', 'Preisfortschreibung bestehender Listenpreise', 'Keine konkreten Supermarkt-Artikelpreise', 'monatlich', 'Bestehende Preise per Index plausibilisieren; nicht direkt als Artikelpreis übernehmen', 'Siehe Destatis VPI / GENESIS', 'empfohlen']]`

## ingredient_prices
- Blatt `Preisliste 2024` mit Confidence `10` und Header-Indizien `[['Zutat', 'Preis', 'Einheit'], ['Apfel', '3.95', '€/kg']]`
- Blatt `Preisliste` mit Confidence `18` und Header-Indizien `[['Zutat', 'Preis', 'Einheit', 'Status', 'Quelle / Shop', 'Stand', 'Preisnotiz'], ['Apfel', '1.59', '€/kg', 'OK']]`
- Blatt `Preisquellen & Pflege` mit Confidence `16` und Header-Indizien `[['Quelle', 'Was liefert sie?', 'Eignet sich für', 'Grenze', 'Aktualisierung', 'Nutzung im Workbook', 'Link/Verweis', 'Status'], ['Destatis / GENESIS Verbraucherpreisindex', 'Index- und Veränderungsraten für Lebensmittelgruppen', 'Preisfortschreibung bestehender Listenpreise', 'Keine konkreten Supermarkt-Artikelpreise', 'monatlich', 'Bestehende Preise per Index plausibilisieren; nicht direkt als Artikelpreis übernehmen', 'Siehe Destatis VPI / GENESIS', 'empfohlen']]`

## recipes
- Blatt `Rezepte Übersicht` mit Confidence `3` und Header-Indizien `[]`
- Blatt `Vorlage` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Frühstück Kinder` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '186'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Frühstück Betreuer` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '69'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Vegi Lasagne` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss, Zucker)', 'Portionen:', '10'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Veggi-Soße']]`
- Blatt `Lasagne Fl.` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss, Zucker)', 'Portionen:', '6'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Hackfleischsoße']]`
- Blatt `Brotzeit` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss, Zucker)', 'Portionen:', '25'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Brot']]`
- Blatt `Käsespätzle` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss)', 'Portionen:', '20'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Spätzle']]`
- Blatt `Kaiserschmarrn` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Salz )', 'Portionen:', '90']]`
- Blatt `Chili con Carne` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Cayennepfeffer, Paprika., Kreuzkümmel )', 'Portionen:', '95']]`
- Blatt `Chili sin Carne` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Cayennepfeffer, Paprika., Kreuzkümmel )', 'Portionen:', '20'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Chili sin Carne']]`
- Blatt `Veggi Burger` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Paprikapulver, Salz, Pfeffer)', 'Portionen:', '110'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Paddies']]`
- Blatt `Sphageti Bolognese` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Oregano, Salz, Pfeffer)', 'Portionen:', '95']]`
- Blatt `Gemüse Nudeln` mit Confidence `8` und Header-Indizien `[['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Gemüsenudeln']]`
- Blatt `Soja Geschnezeltes` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Fleischpflanzerl&KAPÜ` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Majoran, Salz, Pfeffer, Muskat )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Fleischpflanzerl']]`
- Blatt `Gnocci mit Spinat Frischkäse` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Gemüsebrühe, Muskat, Salz, Pfeffer)', 'Portionen:', '95']]`
- Blatt `Gnocchi Salat` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '23']]`
- Blatt `Rahmgulasch mit SK` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Paprika edelsüß, Paprika rosenscharf, Majoran, Lorbeerblatt )', 'Portionen:', '95']]`
- Blatt `Spaghetti Napoli` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Oregano, Basilikum, Salz, Pfeffer)', 'Portionen:', '20'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Smashed Burger` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '22']]`
- Blatt `Tortelini Salat` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '23']]`
- Blatt `Wiener mit Semmel` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '90']]`
- Blatt `Salat Beilage` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '93'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Gurkensalat` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '93']]`
- Blatt `Tiroler Gröstl` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '25'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Rippchen am Grill` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '25'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Couscous Salat` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Gemüse Curry` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '95']]`
- Blatt `Couscous Pfanne mit Feta` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Paprika Reispfanne ` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Paprika-Hackpfanne` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Züricher Geschnetzeltes` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer)', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Geschnetzeltes']]`
- Blatt `Ratatouilles con Boeuf` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Thymian, Rosmarin,Lorbeerblatt)', 'Portionen:', '23'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Karottensalat` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: Salz Pfeffer)', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Grüner Salat mit Feta` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Köttbullar` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze:Muskat, Pfeffer )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Köttbullar']]`

## recipe_ingredients
- Blatt `Rezepte Übersicht` mit Confidence `3` und Header-Indizien `[]`
- Blatt `Vorlage` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Frühstück Kinder` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '186'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Frühstück Betreuer` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '69'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Vegi Lasagne` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss, Zucker)', 'Portionen:', '10'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Veggi-Soße']]`
- Blatt `Lasagne Fl.` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss, Zucker)', 'Portionen:', '6'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Hackfleischsoße']]`
- Blatt `Brotzeit` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss, Zucker)', 'Portionen:', '25'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Brot']]`
- Blatt `Käsespätzle` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer, Muskatnuss)', 'Portionen:', '20'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Spätzle']]`
- Blatt `Kaiserschmarrn` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Salz )', 'Portionen:', '90']]`
- Blatt `Chili con Carne` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Cayennepfeffer, Paprika., Kreuzkümmel )', 'Portionen:', '95']]`
- Blatt `Chili sin Carne` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Cayennepfeffer, Paprika., Kreuzkümmel )', 'Portionen:', '20'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Chili sin Carne']]`
- Blatt `Veggi Burger` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Paprikapulver, Salz, Pfeffer)', 'Portionen:', '110'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Paddies']]`
- Blatt `Sphageti Bolognese` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Oregano, Salz, Pfeffer)', 'Portionen:', '95']]`
- Blatt `Gemüse Nudeln` mit Confidence `8` und Header-Indizien `[['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Gemüsenudeln']]`
- Blatt `Soja Geschnezeltes` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Fleischpflanzerl&KAPÜ` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Majoran, Salz, Pfeffer, Muskat )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Fleischpflanzerl']]`
- Blatt `Gnocci mit Spinat Frischkäse` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Gemüsebrühe, Muskat, Salz, Pfeffer)', 'Portionen:', '95']]`
- Blatt `Gnocchi Salat` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '23']]`
- Blatt `Rahmgulasch mit SK` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: Paprika edelsüß, Paprika rosenscharf, Majoran, Lorbeerblatt )', 'Portionen:', '95']]`
- Blatt `Spaghetti Napoli` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Oregano, Basilikum, Salz, Pfeffer)', 'Portionen:', '20'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Smashed Burger` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '22']]`
- Blatt `Tortelini Salat` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '23']]`
- Blatt `Wiener mit Semmel` mit Confidence `10` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '90']]`
- Blatt `Salat Beilage` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '93'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Gurkensalat` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '93']]`
- Blatt `Tiroler Gröstl` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '25'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Rippchen am Grill` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '25'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Couscous Salat` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Gemüse Curry` mit Confidence `13` und Header-Indizien `[['Rezept für:', 'angepasst'], ['Zutaten:  (Gewürze: )', 'Portionen:', '95']]`
- Blatt `Couscous Pfanne mit Feta` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Paprika Reispfanne ` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Paprika-Hackpfanne` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Züricher Geschnetzeltes` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Salz, Pfeffer)', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Geschnetzeltes']]`
- Blatt `Ratatouilles con Boeuf` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze: Thymian, Rosmarin,Lorbeerblatt)', 'Portionen:', '23'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Karottensalat` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: Salz Pfeffer)', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Grüner Salat mit Feta` mit Confidence `13` und Header-Indizien `[['Zutaten:  (Gewürze: )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:']]`
- Blatt `Köttbullar` mit Confidence `10` und Header-Indizien `[['Zutaten:  (Gewürze:Muskat, Pfeffer )', 'Portionen:', '100'], ['Zutaten:', 'Grundmenge:', 'Einheit:', 'Gesamtmenge', 'Preis/kg:', 'Gesamtpreis:', 'Köttbullar']]`

## meal_plan_entries
- Blatt `Planung 2026` mit Confidence `20` und Header-Indizien `[['Zeltlager Verpflegungsplanung 2026', 'Rezeptliste'], ['Jahr', 'Startdatum', 'Enddatum', 'Geplante Tage', 'Geplante Rezepte', 'Geplante Portionen', 'Budget geplant', 'Ø Kosten / Portion', 'Einkäufe offen', 'Letzte Änderung', 'Notiz', 'Chili con Carne']]`

## recipe_feedback
- Blatt `Rezept Feedback` mit Confidence `15` und Header-Indizien `[['Jahr', 'Rezept', 'Bewertung 1-5', 'Wiederholen?', 'Portionen geplant', 'Portionen gekocht', 'Übrig geblieben', 'Einheit Rest', 'Mengenfaktor nächstes Mal', 'Ablauf-Tipps / Tricks', 'Was lief gut?', 'Was ändern?']]`

## shopping_list_items
- Blatt `Einkaufsliste 2024` mit Confidence `9` und Header-Indizien `[['Zutat', 'Menge', 'Einheit', 'Preis pro Einheit', 'Gesamtpreis', 'Gerichte']]`
- Blatt `Einkaufsliste 2025` mit Confidence `9` und Header-Indizien `[['Zutat', 'Menge', 'Einheit', 'Preis pro Einheit', 'Gesamtpreis', 'Gerichte']]`
- Blatt `Einkaufsplanung` mit Confidence `17` und Header-Indizien `[['Gesamtkosten', 'Offene Artikel', 'Erledigte Artikel', 'Artikel ohne Preis', 'Frische-Artikel heute', 'Notiz'], ['Zutat', 'Menge', 'Einheit', 'Preis / Einheit', 'Preis fehlt?', 'Gerichte', 'Gesamtpreis', 'Einkaufstag', 'Kategorie / Lager', 'Status', 'Notiz / Laden']]`

## unclassified_sheets
- Keine Zuordnung erkannt
