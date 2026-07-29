from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientPrice


@dataclass(slots=True)
class PriceComparisonRow:
    ingredient: Ingredient
    price_a: Decimal | None
    price_b: Decimal | None
    difference: Decimal | None
    percent_change: Decimal | None


UNIT_ALIASES = {
    "kg": "kg",
    "g": "g",
    "gramm": "g",
    "gr": "g",
    "l": "l",
    "liter": "l",
    "lt": "l",
    "ml": "ml",
    "stk": "stk",
    "stueck": "stk",
    "stück": "stk",
    "pcs": "stk",
    "piece": "stk",
}

# Durchschnittliche Grammzahlen fuer gebraeuchliche Kuechenmasse (Zehe, Loeffel, Prise, ...).
# Das sind bewusst grobe Naeherungswerte fuer die Grosseinkauf-Kalkulation (Beschaffung soll in
# kg/l erfolgen koennen, auch wenn Rezepte weiterhin die kuechenuebliche Einheit verwenden) - keine
# praezisen, zutatenspezifischen Dichten. Quelle: gaengige deutsche Kuechen-Umrechnungstabellen
# (z. B. EAT SMARTER, Chefkoch-Referenzwerte).
#   - Zehe (Knoblauchzehe): ~5 g
#   - EL (Esslöffel, gehäuft, trockene Zutat wie Zucker/Mehl): ~15 g
#   - TL (Teelöffel, gehäuft): ~5 g
#   - Prise: ~0.5 g
#   - Bund (Kraeuterbund, z. B. Petersilie): ~50 g
#   - Scheibe (z. B. Brot/Kaese): ~25 g
#   - Blatt (hier ausschliesslich als Lorbeerblatt verwendet): ~0.15 g
# "Stk", "Glas", "Dose", "Packung" bekommen bewusst KEINEN Pauschalfaktor - die Groesse eines
# Stuecks/einer Packung schwankt zu stark zwischen Zutaten (ein Ei vs. eine Wassermelone), das muss
# je Zutat ueber die tatsaechliche Standardeinheit/Paketgroesse (z. B. per Open Prices) geloest werden.
UNIT_FACTORS = {
    "g": ("mass", Decimal("1")),
    "kg": ("mass", Decimal("1000")),
    "zehe": ("mass", Decimal("5")),
    "el": ("mass", Decimal("15")),
    "tl": ("mass", Decimal("5")),
    "prise": ("mass", Decimal("0.5")),
    "bund": ("mass", Decimal("50")),
    "scheibe": ("mass", Decimal("25")),
    "blatt": ("mass", Decimal("0.15")),
    "ml": ("volume", Decimal("1")),
    "l": ("volume", Decimal("1000")),
    "stk": ("count", Decimal("1")),
}


def find_best_price(
    session: Session,
    ingredient_id: int,
    *,
    year: int | None = None,
    fallback_latest: bool = True,
) -> IngredientPrice | None:
    """Bester Preis fuer eine Zutat: exakter Jahrestreffer, sonst der neueste bekannte Preis."""
    prices = session.execute(
        select(IngredientPrice).where(IngredientPrice.ingredient_id == ingredient_id)
    ).scalars().all()
    if not prices:
        return None

    if year is not None:
        exact_matches = [price for price in prices if price.year == year]
        if exact_matches:
            return max(exact_matches, key=_price_sort_key)
        if not fallback_latest:
            return None

    return find_latest_price_from(prices)


def find_latest_price(session: Session, ingredient_id: int) -> IngredientPrice | None:
    prices = session.execute(
        select(IngredientPrice).where(IngredientPrice.ingredient_id == ingredient_id)
    ).scalars().all()
    return find_latest_price_from(prices)


def find_latest_price_from(prices: list[IngredientPrice]) -> IngredientPrice | None:
    if not prices:
        return None
    return max(prices, key=_price_sort_key)


def _price_sort_key(price: IngredientPrice) -> tuple:
    return (
        price.valid_from or (price.updated_at.date() if price.updated_at else None),
        price.year or 0,
        price.id or 0,
    )


def missing_price_ingredients(session: Session, *, year: int | None = None, active_only: bool = True) -> list[Ingredient]:
    """Zutaten ohne (gueltigen) Preis fuer das angegebene Jahr, bzw. ganz ohne Preis."""
    stmt = select(Ingredient)
    if active_only:
        stmt = stmt.where(Ingredient.active.is_(True))
    ingredients = session.execute(stmt).scalars().all()

    missing = []
    for ingredient in ingredients:
        if year is not None:
            has_price = any(price.year == year for price in ingredient.prices)
        else:
            has_price = len(ingredient.prices) > 0
        if not has_price:
            missing.append(ingredient)
    return missing


def copy_prices_from_year(
    session: Session,
    *,
    source_year: int,
    target_year: int,
    overwrite: bool = False,
) -> int:
    """Kopiert Preise von einem Jahr in ein anderes fuer Zutaten, denen im Zieljahr ein Preis fehlt."""
    source_prices = session.execute(
        select(IngredientPrice).where(IngredientPrice.year == source_year)
    ).scalars().all()

    copied = 0
    for source_price in source_prices:
        existing_target = session.execute(
            select(IngredientPrice).where(
                IngredientPrice.ingredient_id == source_price.ingredient_id,
                IngredientPrice.year == target_year,
            )
        ).scalars().all()
        if existing_target and not overwrite:
            continue
        if existing_target and overwrite:
            for old_price in existing_target:
                session.delete(old_price)

        session.add(
            IngredientPrice(
                ingredient_id=source_price.ingredient_id,
                price_per_unit=source_price.price_per_unit,
                unit=source_price.unit,
                source=source_price.source,
                store=source_price.store,
                year=target_year,
                confidence="uebernommen",
                notes=f"Kopiert aus {source_year}",
            )
        )
        copied += 1
    return copied


def delete_price(session: Session, price: IngredientPrice) -> None:
    session.delete(price)


def compare_years(session: Session, *, year_a: int, year_b: int) -> list[PriceComparisonRow]:
    ingredients = session.execute(select(Ingredient).order_by(Ingredient.name)).scalars().all()
    rows: list[PriceComparisonRow] = []
    for ingredient in ingredients:
        price_a = next((p.price_per_unit for p in ingredient.prices if p.year == year_a), None)
        price_b = next((p.price_per_unit for p in ingredient.prices if p.year == year_b), None)
        if price_a is None and price_b is None:
            continue
        difference = (price_b - price_a) if price_a is not None and price_b is not None else None
        percent_change = None
        if difference is not None and price_a:
            percent_change = (difference / price_a) * Decimal("100")
        rows.append(
            PriceComparisonRow(
                ingredient=ingredient,
                price_a=price_a,
                price_b=price_b,
                difference=difference,
                percent_change=percent_change,
            )
        )
    return rows


def normalize_unit(unit: str | None) -> str | None:
    if unit is None:
        return None
    normalized = unit.strip().lower()
    normalized = normalized.replace("€", "eur").replace("euro", "eur")
    normalized = normalized.replace(" ", "")
    for prefix in ("eur/", "eurpro", "preis/", "price/", "/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    if normalized.startswith("pro"):
        normalized = normalized[3:]
    return UNIT_ALIASES.get(normalized, normalized or None)


def can_convert_units(from_unit: str | None, to_unit: str | None) -> bool:
    normalized_from = normalize_unit(from_unit)
    normalized_to = normalize_unit(to_unit)
    if not normalized_from or not normalized_to:
        return False
    if normalized_from == normalized_to:
        return True
    from_meta = UNIT_FACTORS.get(normalized_from)
    to_meta = UNIT_FACTORS.get(normalized_to)
    return bool(from_meta and to_meta and from_meta[0] == to_meta[0])


def convert_quantity(quantity: Decimal, *, from_unit: str, to_unit: str) -> Decimal:
    normalized_from = normalize_unit(from_unit)
    normalized_to = normalize_unit(to_unit)
    if normalized_from == normalized_to:
        return quantity

    from_meta = UNIT_FACTORS.get(normalized_from or "")
    to_meta = UNIT_FACTORS.get(normalized_to or "")
    if from_meta is None or to_meta is None or from_meta[0] != to_meta[0]:
        raise ValueError(f"Einheiten sind nicht kompatibel: {from_unit} -> {to_unit}")

    base_quantity = quantity * from_meta[1]
    return base_quantity / to_meta[1]


def convert_price_per_unit(price_per_unit: Decimal, *, from_unit: str, to_unit: str) -> Decimal:
    normalized_from = normalize_unit(from_unit)
    normalized_to = normalize_unit(to_unit)
    if normalized_from == normalized_to:
        return price_per_unit

    from_meta = UNIT_FACTORS.get(normalized_from or "")
    to_meta = UNIT_FACTORS.get(normalized_to or "")
    if from_meta is None or to_meta is None or from_meta[0] != to_meta[0]:
        raise ValueError(f"Einheiten sind nicht kompatibel: {from_unit} -> {to_unit}")

    base_units_per_from_unit = from_meta[1]
    base_units_per_to_unit = to_meta[1]
    return price_per_unit * (base_units_per_to_unit / base_units_per_from_unit)
