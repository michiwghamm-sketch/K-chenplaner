# Einheiten-Bereinigung

- Ausgefuehrt am: 2026-07-25T14:26:09+02:00
- Modus: angewendet
- Backup: D:\Kolping\ZelaKüche_Programm\backups\zeltlager_kueche_20260725_142608.sqlite3
- Bereinigte Wertevarianten: 22 (betrifft 438 Datensätze)
- Nicht automatisch zuordenbare Werte: 0
- Rezeptzutaten mit weiterhin inkompatibler Einheit: 20

## Bereinigte Wertevarianten

| Feld | Alter Wert | Neuer Wert | Anzahl Datensätze |
| --- | --- | --- | --- |
| ingredient_prices.unit | `stk` | `Stk` | 1 |
| ingredient_prices.unit | `€/Stk` | `Stk` | 14 |
| ingredient_prices.unit | `€/kg` | `kg` | 179 |
| ingredient_prices.unit | `€/l` | `l` | 32 |
| ingredients.default_unit | `€/Stk` | `Stk` | 9 |
| ingredients.default_unit | `€/Zehe` | `Zehe` | 1 |
| ingredients.default_unit | `€/kg` | `kg` | 106 |
| ingredients.default_unit | `€/l` | `l` | 21 |
| recipe_ingredients.price_unit | `STK` | `Stk` | 1 |
| recipe_ingredients.price_unit | `Zehen` | `Zehe` | 6 |
| recipe_ingredients.price_unit | `kl` | `l` | 2 |
| recipe_ingredients.price_unit | `€/kg` | `kg` | 18 |
| recipe_ingredients.price_unit | `€/l` | `l` | 1 |
| recipe_ingredients.unit | `Zehen` | `Zehe` | 6 |
| recipe_ingredients.unit | `kl` | `l` | 2 |
| recipe_ingredients.unit | `€/kg` | `kg` | 18 |
| recipe_ingredients.unit | `€/l` | `l` | 2 |
| shopping_list_items.unit | `glas` | `Glas` | 1 |
| shopping_list_items.unit | `kl` | `l` | 1 |
| shopping_list_items.unit | `stk` | `Stk` | 11 |
| shopping_list_items.unit | `zehe` | `Zehe` | 3 |
| shopping_list_items.unit | `zehen` | `Zehe` | 3 |

## Nicht automatisch zuordenbare Werte

Keine.

## Rezeptzutaten mit weiterhin inkompatibler Einheit

Diese Rezeptzutaten verwenden nach der Bereinigung eine Einheit, die nicht zur Standardeinheit ihrer Zutat passt (z. B. unterschiedliche Art wie Masse vs. Stueck). Bitte in der Rezeptansicht pruefen und die Menge/Einheit oder die Standardeinheit der Zutat korrigieren.

| Zutat | Rezept | Verwendete Einheit | Standardeinheit der Zutat |
| --- | --- | --- | --- |
| Currrypaste | Gemüse Curry | l | kg |
| Gemüsebrühe | Gnocci mit Spinat Frischkäse | l | kg |
| Gemüsebrühe | Spaghetti Napoli | l | kg |
| Knoblauch | Couscous Pfanne mit Feta | Stk | Zehe |
| Knoblauch | Couscous Pfanne mit Feta | Stk | Zehe |
| Knoblauch | Paprika Reispfanne | kg | Zehe |
| Knoblauch | Paprika Reispfanne | kg | Zehe |
| Knoblauch | Paprika-Hackpfanne | kg | Zehe |
| Lorbeerblatt | Rahmgulasch mit Serviettenknödeln | Stk | kg |
| Majonaise | Smashed Burger | kg | l |
| Majonaise | Smashed Burger (Vegetarisch) | kg | l |
| Majonaise | Veggi Burger | kg | l |
| Rinderbrühe | Lasagne mit Fleisch | l | kg |
| Rinderbrühe | Lasagne mitGemüse | l | kg |
| Rinderbrühe | Rahmgulasch mit Serviettenknödeln | l | kg |
| Rinderbrühe | Sphageti Bolognese | l | kg |
| Salat | Veggi Burger | kg | Stk |
| Tomaten, passiert | Spaghetti Napoli | l | kg |
| Tomaten, passiert | Sphageti Bolognese | l | kg |
| Wiener | Wiener mit Semmel | kg | Stk |
