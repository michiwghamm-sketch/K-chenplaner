from __future__ import annotations

from decimal import Decimal, InvalidOperation


UNIT_ALIASES = {
    "kg ": "kg",
    "Kg": "kg",
    "stk.": "Stk",
    "stück": "Stk",
    "Stück": "Stk",
    "stk": "Stk",
    "l ": "l",
    "L": "l",
}


def normalize_unit(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    if not cleaned:
        return None
    return UNIT_ALIASES.get(cleaned, cleaned)


def parse_decimal(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
