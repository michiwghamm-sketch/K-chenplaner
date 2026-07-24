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


def search_ingredients(
    session: Session, *, query: str | None = None, active_only: bool = True, without_price: bool = False
) -> list[Ingredient]:
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
    if without_price:
        ingredients = [ingredient for ingredient in ingredients if not ingredient.prices]
    return ingredients


def generate_unique_ingredient_name(session: Session, base_name: str = "Neue Zutat") -> str:
    """Findet einen freien Namen für eine neue Zutat (z. B. wenn 'Neue Zutat' bereits existiert)."""
    candidate = base_name
    counter = 2
    while session.execute(select(Ingredient).where(Ingredient.normalized_name == normalize_name(candidate))).scalar_one_or_none() is not None:
        candidate = f"{base_name} {counter}"
        counter += 1
    return candidate


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


def delete_ingredient(session: Session, ingredient: Ingredient) -> None:
    """Löscht eine Zutat dauerhaft. Schlägt fehl, wenn sie noch in mindestens einem Rezept
    verwendet wird (dort würden sonst verwaiste Zutatenverknüpfungen entstehen) - in dem Fall
    stattdessen deaktivieren oder zuerst aus den betroffenen Rezepten entfernen."""
    if ingredient.recipe_links:
        recipe_names = sorted({link.recipe.name for link in ingredient.recipe_links})
        raise ValueError(
            f"'{ingredient.name}' wird noch in folgenden Rezepten verwendet und kann nicht gelöscht werden: "
            f"{', '.join(recipe_names)}. Bitte zuerst aus den Rezepten entfernen oder stattdessen deaktivieren."
        )
    session.delete(ingredient)
    session.flush()


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


def _match_reason(normalized_a: str, normalized_b: str, *, threshold: float) -> tuple[str, float] | None:
    """Prueft, ob zwei normalisierte Namen als Dublette gelten (Singular/Plural oder hohe Aehnlichkeit).

    Gibt (Grund, Aehnlichkeit) zurueck, oder None wenn kein Match. Zentrale Stelle fuer die
    Aehnlichkeitslogik, damit find_merge_candidates() und find_similar_ingredients() (Dublettenschutz
    beim Neuanlegen) nicht auseinanderlaufen.
    """
    is_plural = _is_plural_variant(normalized_a, normalized_b)
    similarity = difflib.SequenceMatcher(None, normalized_a, normalized_b).ratio()
    if not is_plural and similarity < threshold:
        return None
    reason = "Singular/Plural-Variante" if is_plural else f"sehr hohe Namensähnlichkeit ({similarity:.0%})"
    return reason, similarity


def find_similar_ingredients(
    session: Session,
    name: str,
    *,
    exclude_id: int | None = None,
    active_only: bool = True,
    threshold: float = AUTO_MERGE_SIMILARITY_THRESHOLD,
) -> list[tuple[Ingredient, float, str]]:
    """Findet aktive Zutaten, deren Name dem gegebenen Namen sehr aehnlich ist (Tippfehler, Singular/Plural).

    Zentrale Aehnlichkeitspruefung fuer eine einzelne Zutat gegen den restlichen Bestand - genutzt
    sowohl von find_merge_candidates() (paarweise ueber alle Zutaten) als auch vom Dublettenschutz
    beim Anlegen/Umbenennen einer Zutat in der UI. Gibt (Zutat, Aehnlichkeit, Grund)-Tupel zurueck,
    absteigend nach Aehnlichkeit sortiert.
    """
    normalized_name = normalize_name(name)
    stmt = select(Ingredient)
    if active_only:
        stmt = stmt.where(Ingredient.active.is_(True))
    ingredients = session.execute(stmt).scalars().all()

    matches: list[tuple[Ingredient, float, str]] = []
    for candidate in ingredients:
        if exclude_id is not None and candidate.id == exclude_id:
            continue
        if candidate.normalized_name == normalized_name:
            continue
        match = _match_reason(normalized_name, candidate.normalized_name, threshold=threshold)
        if match is None:
            continue
        reason, similarity = match
        matches.append((candidate, similarity, reason))

    matches.sort(key=lambda item: item[1], reverse=True)
    return matches


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

    for first in ingredients:
        first_alias_names = {normalize_name(a.alias) for a in first.aliases}
        for second, similarity, reason in find_similar_ingredients(
            session, first.name, exclude_id=first.id, active_only=active_only
        ):
            pair_key = frozenset((first.id, second.id))
            if pair_key in seen_pairs:
                continue
            second_alias_names = {normalize_name(a.alias) for a in second.aliases}
            if second.normalized_name in first_alias_names or first.normalized_name in second_alias_names:
                continue

            seen_pairs.add(pair_key)
            keep, remove = (first, second) if _usage_score(first) >= _usage_score(second) else (second, first)
            candidates.append(MergeCandidate(keep=keep, remove=remove, reason=reason, similarity=similarity))

    return candidates


def find_alias_orphan_candidates(session: Session, *, active_only: bool = True) -> list[MergeCandidate]:
    """Findet Zutaten, bei denen ein Alias bereits auf eine andere Zutat verweist, die eigentliche
    Dublette als separate Ingredient-Zeile aber nie geloescht wurde.

    Das passiert z. B., wenn ein frueherer Merge-Lauf Aliase gesetzt hat, ein anschliessender
    Reimport/Restore aber den Vor-Merge-Datenstand zurueckgebracht hat. Da ein Mensch die
    Zusammengehoerigkeit durch den Alias bereits bestaetigt hat, ist das die sicherste Kandidatenstufe
    (similarity=1.0) - unabhaengig von jeder Namensaehnlichkeit.
    """
    aliases = session.execute(select(IngredientAlias)).scalars().all()
    candidates: list[MergeCandidate] = []
    seen_pairs: set[frozenset[int]] = set()

    for alias in aliases:
        owner = alias.ingredient
        if active_only and not owner.active:
            continue
        stmt = select(Ingredient).where(Ingredient.name == alias.alias, Ingredient.id != owner.id)
        if active_only:
            stmt = stmt.where(Ingredient.active.is_(True))
        duplicate = session.execute(stmt).scalar_one_or_none()
        if duplicate is None:
            continue

        pair_key = frozenset((owner.id, duplicate.id))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)
        candidates.append(
            MergeCandidate(
                keep=owner,
                remove=duplicate,
                reason="Alias verweist bereits auf diese Zutat, Dublette wurde aber nie geloescht",
                similarity=1.0,
            )
        )

    return candidates


def describe_recipe_usage(ingredient: Ingredient) -> list[str]:
    """Menschlich lesbare Liste der Rezepte, die diese Zutat verwenden (Name + Menge/Einheit)."""
    return [f"{link.recipe.name} ({link.quantity} {link.unit})" for link in ingredient.recipe_links]


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
