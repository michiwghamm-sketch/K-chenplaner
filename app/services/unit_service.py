from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientPrice, RecipeIngredient, ShoppingListItem, Unit

# Ausgangsbestand des Einheiten-Pools. 'kind' gruppiert ineinander umrechenbare Einheiten.
# Zehe/EL/TL/Prise/Bund/Scheibe gehoeren zur 'mass'-Gruppe wie g/kg, weil dafuer in
# price_service.UNIT_FACTORS feste Grammnaeherungen hinterlegt sind (z. B. 1 Zehe ~ 5 g) - so
# koennen Rezepte weiterhin kuechenuebliche Einheiten verwenden, waehrend Preise/Beschaffung in
# kg/l gepflegt werden (siehe price_service.py fuer die Werte samt Quellenangabe). 'Blatt' ist
# ebenfalls 'mass' (ausschliesslich als Lorbeerblatt verwendet, ~0.15 g). 'Glas'/'Dose'/'Packung'
# bleiben bewusst eigene, nicht umrechenbare Einheiten - ihre Groesse schwankt zu stark zwischen
# Produkten, um pauschal in Gramm/ml auszudruecken.
DEFAULT_UNITS: list[tuple[str, str, int]] = [
    ("g", "mass", 10),
    ("kg", "mass", 20),
    ("ml", "volume", 30),
    ("l", "volume", 40),
    ("Stk", "count", 50),
    ("Bund", "mass", 60),
    ("Zehe", "mass", 70),
    ("Prise", "mass", 80),
    ("EL", "mass", 90),
    ("TL", "mass", 100),
    ("Glas", "glas", 110),
    ("Dose", "dose", 120),
    ("Packung", "packung", 130),
    ("Scheibe", "mass", 140),
    ("Blatt", "mass", 150),
]

# Bekannte Schreib-/Pluralvarianten, die beim Bereinigen alter Daten auf die Pool-Schreibweise
# abgebildet werden, falls kein direkter (case-insensitiver) Treffer im Pool existiert.
# "kl" ist ein dokumentierter Tippfehler aus den Altdaten (siehe scripts/cleanup_units.py) - kein
# eigenstaendiges Einheitenkuerzel.
_ALIASES: dict[str, str] = {
    "zehen": "Zehe",
    "stk.": "Stk",
    "stück": "Stk",
    "stueck": "Stk",
    "gramm": "g",
    "liter": "l",
    "ltr": "l",
    "kl": "l",
}

_DEFAULT_UNIT_NAMES_BY_LOWER = {name.lower(): name for name, _kind, _sort_order in DEFAULT_UNITS}

_UNIT_COLUMNS = (
    (Ingredient, "default_unit"),
    (RecipeIngredient, "unit"),
    (RecipeIngredient, "price_unit"),
    (IngredientPrice, "unit"),
    (ShoppingListItem, "unit"),
)


def ensure_default_units(session: Session) -> None:
    """Legt den Ausgangsbestand an Einheiten an, falls sie noch fehlen, und haelt die 'kind'-
    Gruppierung mitgelieferter Einheiten synchron mit DEFAULT_UNITS. Idempotent.

    Der Sync ist noetig, weil sich die Gruppierung einer eingebauten Einheit mit neuen
    Erkenntnissen aendern kann (z. B. wurden Zehe/EL/TL/Prise/Bund/Scheibe nachtraeglich der
    'mass'-Gruppe zugeordnet, damit sie gegen kg/g umrechenbar sind - siehe price_service.py).
    Nur Namen, die in DEFAULT_UNITS vorkommen, werden angefasst - eigene, spaeter im Pool
    hinzugefuegte Einheiten bleiben unberuehrt.
    """
    existing_by_lower = {unit.name.lower(): unit for unit in session.execute(select(Unit)).scalars().all()}
    changed = False
    for name, kind, sort_order in DEFAULT_UNITS:
        existing = existing_by_lower.get(name.lower())
        if existing is None:
            session.add(Unit(name=name, kind=kind, sort_order=sort_order, active=True))
            changed = True
        elif existing.kind != kind:
            existing.kind = kind
            changed = True
    if changed:
        session.flush()


def list_units(session: Session, *, active_only: bool = True) -> list[Unit]:
    stmt = select(Unit).order_by(Unit.sort_order, Unit.name)
    if active_only:
        stmt = stmt.where(Unit.active.is_(True))
    return session.execute(stmt).scalars().all()


def list_unit_names(session: Session, *, active_only: bool = True) -> list[str]:
    return [unit.name for unit in list_units(session, active_only=active_only)]


def find_unit(session: Session, name: str | None, *, active_only: bool = False) -> Unit | None:
    if not name:
        return None
    stmt = select(Unit).where(func.lower(Unit.name) == name.strip().lower())
    if active_only:
        stmt = stmt.where(Unit.active.is_(True))
    return session.execute(stmt).scalar_one_or_none()


def _strip_price_prefix(value: str) -> str:
    """Entfernt Preis-Praefixe wie '€/', 'EUR/', 'Preis/' - das ist die Wurzel der urspruenglichen
    Datenverschmutzung (siehe scripts/cleanup_units.py)."""
    lowered = value.strip().lower().replace(" ", "")
    lowered = lowered.replace("€", "eur").replace("euro", "eur")
    for prefix in ("eur/", "eurpro", "preis/", "price/", "/"):
        if lowered.startswith(prefix):
            lowered = lowered[len(prefix) :]
            break
    if lowered.startswith("pro"):
        lowered = lowered[3:]
    return lowered


def canonicalize(session: Session, raw: str | None) -> str | None:
    """Bildet einen freien Eingabewert bestmoeglich auf die Pool-Schreibweise ab.

    Wirft nie einen Fehler - fuer strenge Pruefung siehe validate_unit(). Unbekannte Werte werden
    nur getrimmt (ohne Preis-Praefix) zurueckgegeben, damit Aufrufer wie der Open-Prices-Import
    nicht an unerwarteten externen Einheiten scheitern.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None

    stripped = _strip_price_prefix(cleaned)
    if not stripped:
        return None

    direct = find_unit(session, stripped)
    if direct is not None:
        return direct.name

    alias_target = _ALIASES.get(stripped)
    if alias_target is not None:
        aliased = find_unit(session, alias_target)
        if aliased is not None:
            return aliased.name
        return alias_target

    return stripped


def canonicalize_static(raw: str | None) -> str | None:
    """Wie canonicalize(), aber ohne Datenbankzugriff - nur gegen den eingebauten
    Basis-Einheitenbestand (DEFAULT_UNITS), nicht gegen spaeter im Pool ergaenzte Einheiten.

    Fuer Stellen ohne Session, z. B. die reinen Open-Prices-Konvertierungsfunktionen, die nur mit
    den immer vorhandenen Basis-Einheiten (kg, g, l, ml, Stk) umgehen.
    """
    if raw is None:
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    stripped = _strip_price_prefix(cleaned)
    if not stripped:
        return None
    if stripped in _DEFAULT_UNIT_NAMES_BY_LOWER:
        return _DEFAULT_UNIT_NAMES_BY_LOWER[stripped]
    alias_target = _ALIASES.get(stripped, "").lower()
    if alias_target in _DEFAULT_UNIT_NAMES_BY_LOWER:
        return _DEFAULT_UNIT_NAMES_BY_LOWER[alias_target]
    return stripped


def validate_unit(session: Session, raw: str | None, *, field_label: str = "Einheit") -> str:
    """Wie canonicalize(), wirft aber einen ValueError, wenn das Ergebnis nicht im Pool steht.

    Fuer Felder, die zwingend eine gueltige Poolschreibweise brauchen (z. B. beim Speichern aus der
    UI/den Services) - im Unterschied zu canonicalize(), das fuer Altdaten-Bereinigung/externe
    Importe auch unbekannte Werte bestmoeglich durchreicht.
    """
    canonical = canonicalize(session, raw)
    if not canonical:
        raise ValueError(f"{field_label} darf nicht leer sein.")
    if find_unit(session, canonical) is None:
        raise ValueError(f"'{raw}' ist keine gültige {field_label} - bitte aus dem Einheiten-Pool wählen.")
    return canonical


def compatible_units(session: Session, base_unit: str | None, *, active_only: bool = True) -> list[str]:
    """Einheiten derselben Art wie base_unit (z. B. kg -> [g, kg]), fuer Rezeptzutaten-Dropdowns.

    Faellt auf [base_unit] zurueck, wenn base_unit nicht im Pool steht (z. B. Altdaten vor der
    Bereinigung), damit der bestehende Wert in der UI nicht verschwindet.
    """
    if not base_unit:
        return []
    units = list_units(session, active_only=active_only)
    base = next((unit for unit in units if unit.name == base_unit), None)
    if base is None:
        return [base_unit]
    return [unit.name for unit in units if unit.kind == base.kind]


# --- Pool-Verwaltung (Einheiten hinzufuegen/umbenennen/entfernen) ------------------------


def add_unit(session: Session, name: str, *, kind: str | None = None) -> Unit:
    cleaned = name.strip()
    if not cleaned:
        raise ValueError("Der Einheitenname darf nicht leer sein.")
    if find_unit(session, cleaned) is not None:
        raise ValueError(f"Die Einheit '{cleaned}' existiert bereits.")

    resolved_kind = kind or cleaned.lower()
    max_sort_order = session.execute(select(func.max(Unit.sort_order))).scalar() or 0
    unit = Unit(name=cleaned, kind=resolved_kind, sort_order=max_sort_order + 10, active=True)
    session.add(unit)
    session.flush()
    return unit


def rename_unit(session: Session, unit: Unit, new_name: str) -> Unit:
    """Benennt eine Einheit um und zieht bestehende Zeilen (Zutaten, Rezeptzutaten, Preise,
    Einkaufslisten), die den alten Namen als freien Text gespeichert haben, automatisch mit -
    sonst wuerde der Pool nach einer Umbenennung nicht mehr zu den historischen Daten passen."""
    cleaned = new_name.strip()
    if not cleaned:
        raise ValueError("Der Einheitenname darf nicht leer sein.")
    existing = find_unit(session, cleaned)
    if existing is not None and existing.id != unit.id:
        raise ValueError(f"Die Einheit '{cleaned}' existiert bereits.")

    old_name = unit.name
    if old_name == cleaned:
        return unit

    for model, column_name in _UNIT_COLUMNS:
        column = getattr(model, column_name)
        session.execute(update(model).where(func.lower(column) == old_name.lower()).values(**{column_name: cleaned}))

    unit.name = cleaned
    session.flush()
    return unit


def deactivate_unit(unit: Unit) -> None:
    unit.active = False


def activate_unit(unit: Unit) -> None:
    unit.active = True


def unit_usage_count(session: Session, unit: Unit) -> int:
    total = 0
    for model, column_name in _UNIT_COLUMNS:
        column = getattr(model, column_name)
        total += session.execute(
            select(func.count()).select_from(model).where(func.lower(column) == unit.name.lower())
        ).scalar_one()
    return total


def delete_unit(session: Session, unit: Unit) -> None:
    """Loescht eine Einheit dauerhaft. Schlaegt fehl, wenn sie noch irgendwo verwendet wird -
    in dem Fall stattdessen deaktivieren, damit bestehende Daten weiter eine gueltige Anzeige
    behalten."""
    usage = unit_usage_count(session, unit)
    if usage:
        raise ValueError(
            f"Die Einheit '{unit.name}' wird noch in {usage} Datensatz/Datensätzen verwendet und kann "
            "nicht gelöscht werden. Bitte stattdessen deaktivieren."
        )
    session.delete(unit)
    session.flush()
