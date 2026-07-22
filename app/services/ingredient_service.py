from __future__ import annotations

import difflib
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientAlias
from app.utils.normalization import normalize_name

# Deutsche Pluralendungen, die bei sonst identischem Namen auf ein Dublettenpaar hindeuten
# (z. B. "zwiebel" / "zwiebeln"). Bewusst konservativ gehalten.
PLURAL_SUFFIXES = ("n", "e", "en")
AUTO_MERGE_SIMILARITY_THRESHOLD = 0.93


def search_ingredients(session: Session, *, query: str | None = None, active_only: bool = True) -> list[Ingredient]:
    stmt = select(Ingredient)
    if active_only:
        stmt = stmt.where(Ingredient.active.is_(True))
    ingredients = session.execute(stmt.order_by(Ingredient.name)).scalars().all()
    if query:
        normalized_query = normalize_name(query)
        ingredients = [
            ingredient
            for ingredient in ingredients
            if normalized_query in ingredient.normalized_name
            or any(normalized_query in normalize_name(alias.alias) for alias in ingredient.aliases)
        ]
    return ingredients


def create_ingredient(
    session: Session,
    *,
    name: str,
    default_unit: str | None = None,
    category: str | None = None,
    storage_type: str | None = None,
    notes: str | None = None,
) -> Ingredient:
    ingredient = Ingredient(
        name=name.strip(),
        normalized_name=normalize_name(name),
        default_unit=default_unit,
        category=category,
        storage_type=storage_type,
        notes=notes,
    )
    session.add(ingredient)
    session.flush()
    return ingredient


def update_ingredient(ingredient: Ingredient, **fields: object) -> Ingredient:
    for key, value in fields.items():
        if not hasattr(ingredient, key):
            raise AttributeError(f"Unbekanntes Zutatenfeld: {key}")
        setattr(ingredient, key, value)
    if "name" in fields:
        ingredient.normalized_name = normalize_name(ingredient.name)
    return ingredient


def deactivate_ingredient(ingredient: Ingredient) -> None:
    ingredient.active = False


def activate_ingredient(ingredient: Ingredient) -> None:
    ingredient.active = True


def add_alias(session: Session, ingredient: Ingredient, alias: str, *, notes: str | None = None) -> IngredientAlias:
    existing = session.execute(
        select(IngredientAlias).where(
            IngredientAlias.ingredient_id == ingredient.id,
            IngredientAlias.alias == alias.strip(),
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    alias_record = IngredientAlias(ingredient=ingredient, alias=alias.strip(), notes=notes)
    session.add(alias_record)
    return alias_record


def remove_alias(session: Session, alias_record: IngredientAlias) -> None:
    session.delete(alias_record)


def find_by_name_or_alias(session: Session, name: str) -> Ingredient | None:
    normalized = normalize_name(name)
    ingredient = session.execute(
        select(Ingredient).where(Ingredient.normalized_name == normalized)
    ).scalar_one_or_none()
    if ingredient is not None:
        return ingredient

    alias_record = session.execute(
        select(IngredientAlias).where(IngredientAlias.alias == name.strip())
    ).scalar_one_or_none()
    return alias_record.ingredient if alias_record else None


# --- Dublettenerkennung und Zusammenfuehrung -----------------------------------------


@dataclass(slots=True)
class MergeCandidate:
    keep: Ingredient
    remove: Ingredient
    reason: str
    similarity: float


def _is_plural_variant(name_a: str, name_b: str) -> bool:
    shorter, longer = sorted((name_a, name_b), key=len)
    if shorter == longer:
        return False
    for suffix in PLURAL_SUFFIXES:
        if longer == shorter + suffix:
            return True
    return False


def _usage_score(ingredient: Ingredient) -> tuple[int, int]:
    return (len(ingredient.recipe_links), len(ingredient.prices))


def find_merge_candidates(session: Session, *, active_only: bool = True) -> list[MergeCandidate]:
    """Findet Zutatenpaare, die mit hoher Sicherheit dieselbe Zutat sind (Singular/Plural, Tippfehler).

    Bewusst konservativer als validation_service.find_duplicate_ingredients_without_alias
    (die dortige Schwelle erzeugt nur einen Hinweis, hier soll automatisch zusammengefuehrt werden).
    """
    stmt = select(Ingredient)
    if active_only:
        stmt = stmt.where(Ingredient.active.is_(True))
    ingredients = session.execute(stmt).scalars().all()

    candidates: list[MergeCandidate] = []
    seen_pairs: set[frozenset[int]] = set()

    for i, first in enumerate(ingredients):
        first_alias_names = {normalize_name(a.alias) for a in first.aliases}
        for second in ingredients[i + 1 :]:
            pair_key = frozenset((first.id, second.id))
            if pair_key in seen_pairs:
                continue
            second_alias_names = {normalize_name(a.alias) for a in second.aliases}
            if second.normalized_name in first_alias_names or first.normalized_name in second_alias_names:
                continue

            is_plural = _is_plural_variant(first.normalized_name, second.normalized_name)
            similarity = difflib.SequenceMatcher(None, first.normalized_name, second.normalized_name).ratio()
            if not is_plural and similarity < AUTO_MERGE_SIMILARITY_THRESHOLD:
                continue

            seen_pairs.add(pair_key)
            keep, remove = (first, second) if _usage_score(first) >= _usage_score(second) else (second, first)
            reason = "Singular/Plural-Variante" if is_plural else f"sehr hohe Namensähnlichkeit ({similarity:.0%})"
            candidates.append(MergeCandidate(keep=keep, remove=remove, reason=reason, similarity=similarity))

    return candidates


def merge_ingredients(session: Session, *, keep: Ingredient, remove: Ingredient) -> None:
    """Fuehrt zwei Zutaten zusammen: 'remove' wird zum Alias von 'keep' und anschliessend geloescht.

    Alle Referenzen (Rezeptzutaten, Preise, Einkaufslisten-Positionen, bestehende Aliase)
    werden vorher auf 'keep' umgehaengt, damit keine Daten verloren gehen.
    """
    if keep.id == remove.id:
        raise ValueError("Eine Zutat kann nicht mit sich selbst zusammengeführt werden.")

    # Bei mehreren Merges in derselben Session/Transaktion kann 'remove' Aliase enthalten,
    # die ein vorheriger merge_ingredients()-Aufruf gerade erst angelegt hat und die wegen
    # autoflush=False noch nicht in der Datenbank stehen - session.delete() scheitert dann
    # mit "not persisted". Erst flushen, damit alles einen echten Datenbank-Zustand hat.
    session.flush()

    add_alias(session, keep, remove.name)
    for alias in list(remove.aliases):
        add_alias(session, keep, alias.alias, notes=alias.notes)
        session.delete(alias)

    for link in list(remove.recipe_links):
        link.ingredient = keep
    for price in list(remove.prices):
        price.ingredient = keep
    for item in list(remove.shopping_items):
        item.ingredient = keep

    if not keep.default_unit and remove.default_unit:
        keep.default_unit = remove.default_unit
    if not keep.category and remove.category:
        keep.category = remove.category
    if not keep.storage_type and remove.storage_type:
        keep.storage_type = remove.storage_type

    session.delete(remove)
