from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from app.models import IngredientPrice
from app.utils.normalization import normalize_name
from app.services import price_service, unit_service

API_BASE_URL = "https://prices.openfoodfacts.org/api/v1"
DEFAULT_TIMEOUT_SECONDS = 15


class OpenPricesError(RuntimeError):
    """Basisklasse fuer Fehler bei der Open-Prices-Anbindung."""


class OpenPricesLookupError(OpenPricesError):
    """Die API war erreichbar, konnte aber kein passendes Produkt liefern."""


class OpenPricesUnavailableError(OpenPricesError):
    """Netzwerk- oder API-Fehler beim Abruf externer Preise."""


@dataclass(slots=True)
class OpenPricesProduct:
    code: str
    name: str
    quantity: str | None
    price_count: int
    image_url: str | None = None
    brands: str | None = None


@dataclass(slots=True)
class OpenPriceObservation:
    product_code: str
    product_name: str
    price: Decimal
    currency: str
    date: date | None
    store_name: str | None
    location_name: str | None
    proof_type: str | None
    price_is_discounted: bool


@dataclass(slots=True)
class OpenPricesLookupResult:
    product: OpenPricesProduct
    observations: list[OpenPriceObservation]

    @property
    def latest_observation(self) -> OpenPriceObservation | None:
        return self.observations[0] if self.observations else None


@dataclass(slots=True)
class OpenPricesSearchMatch:
    product: OpenPricesProduct
    observation: OpenPriceObservation
    score: float
    query_used: str = ""


@dataclass(slots=True)
class OpenPricesSuggestion:
    product: OpenPricesProduct
    observation: OpenPriceObservation
    score: float
    query_used: str = ""


@dataclass(slots=True)
class OpenPricesImportResult:
    ingredient_id: int
    ingredient_name: str
    year: int
    status: str
    message: str
    query_used: str | None = None
    matched_product_name: str | None = None
    matched_product_code: str | None = None
    matched_price: Decimal | None = None
    matched_currency: str | None = None
    matched_date: date | None = None
    suggestions: list[OpenPricesSuggestion] | None = None
    price_record: IngredientPrice | None = None


def lookup_product_prices(
    barcode: str,
    *,
    size: int = 10,
    currency: str | None = "EUR",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> OpenPricesLookupResult:
    normalized_barcode = barcode.strip()
    if not normalized_barcode:
        raise ValueError("Ein Barcode wird benötigt.")

    product_payload = _get_json(f"/products/code/{normalized_barcode}", timeout=timeout)
    product = _parse_product(product_payload)

    params: dict[str, Any] = {"product_code": normalized_barcode, "order_by": "-date", "size": size}
    if currency:
        params["currency"] = currency
    prices_payload = _get_json("/prices", params=params, timeout=timeout)
    observations = [_parse_observation(item) for item in prices_payload.get("items", [])]

    return OpenPricesLookupResult(product=product, observations=observations)


def search_products(
    query: str,
    *,
    size: int = 10,
    order_by: str | None = "-price_count",
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[OpenPricesProduct]:
    normalized_query = query.strip()
    if not normalized_query:
        return []

    # Ohne explizite Sortierung liefert die API Treffer in einer Reihenfolge, die mit
    # tatsaechlich vorhandenen Preisbeobachtungen kaum korreliert - bei generischen Begriffen
    # wie "Apfel" hatten von den ersten 50 Treffern nur 2 ueberhaupt einen Preis (price_count>0),
    # das fruehere Standardverhalten fand daher oft schlicht nichts. Nach price_count absteigend
    # sortieren stellt sicher, dass die Kandidaten, die find_best_match_for_query/
    # suggest_matches_for_query anschliessend bewerten, ueberhaupt Preisdaten haben koennen.
    params: dict[str, Any] = {"product_name__like": normalized_query, "size": size}
    if order_by:
        params["order_by"] = order_by
    payload = _get_json("/products", params=params, timeout=timeout)
    return [_parse_product(item) for item in payload.get("items", [])]


def find_best_match_for_query(
    query: str,
    *,
    target_unit: str | None = None,
    currency: str | None = "EUR",
    search_size: int = 10,
    max_product_checks: int = 5,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> OpenPricesSearchMatch:
    best_match: OpenPricesSearchMatch | None = None
    for candidate_query in build_search_queries(query):
        products = search_products(candidate_query, size=search_size, timeout=timeout)
        candidates = sorted(
            (product for product in products if product.code and product.price_count > 0),
            key=lambda product: _score_product_match(query, product, target_unit=target_unit),
            reverse=True,
        )

        for product in candidates[:max_product_checks]:
            try:
                lookup = lookup_product_prices(product.code, size=1, currency=currency, timeout=timeout)
            except OpenPricesError:
                continue
            observation = lookup.latest_observation
            if observation is None:
                continue

            score = _score_product_match(query, product, target_unit=target_unit)
            match = OpenPricesSearchMatch(
                product=product,
                observation=observation,
                score=score,
                query_used=candidate_query,
            )
            if best_match is None or match.score > best_match.score:
                best_match = match

    if best_match is None:
        raise OpenPricesLookupError(f"Kein passender Open-Prices-Treffer für '{query}' gefunden.")
    return best_match


def suggest_matches_for_query(
    query: str,
    *,
    target_unit: str | None = None,
    currency: str | None = "EUR",
    search_size: int = 10,
    max_product_checks: int = 5,
    limit: int = 3,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> list[OpenPricesSuggestion]:
    suggestions: list[OpenPricesSuggestion] = []
    seen_codes: set[str] = set()

    for candidate_query in build_search_queries(query):
        products = search_products(candidate_query, size=search_size, timeout=timeout)
        candidates = sorted(
            (product for product in products if product.code and product.price_count > 0 and product.code not in seen_codes),
            key=lambda product: _score_product_match(query, product, target_unit=target_unit),
            reverse=True,
        )

        for product in candidates[:max_product_checks]:
            try:
                lookup = lookup_product_prices(product.code, size=1, currency=currency, timeout=timeout)
            except OpenPricesError:
                continue
            observation = lookup.latest_observation
            if observation is None:
                continue
            seen_codes.add(product.code)
            suggestions.append(
                OpenPricesSuggestion(
                    product=product,
                    observation=observation,
                    score=_score_product_match(query, product, target_unit=target_unit),
                    query_used=candidate_query,
                )
            )

    suggestions.sort(key=lambda item: item.score, reverse=True)
    return suggestions[:limit]


def import_price_for_ingredient(
    ingredient_id: int,
    ingredient_name: str,
    *,
    target_unit: str | None,
    year: int,
    currency: str | None = "EUR",
    notes_prefix: str | None = None,
    barcode: str | None = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
) -> OpenPricesImportResult:
    if barcode:
        # Die Zutat ist bereits einem konkreten Produkt zugeordnet - direkter, eindeutiger Treffer
        # statt Namens-Fuzzy-Suche. Schlaegt der Barcode fehl (z. B. Produkt ohne Preisdaten),
        # faellt die Funktion unten auf die normale Namenssuche zurueck statt komplett zu scheitern.
        try:
            lookup = lookup_product_prices(barcode, currency=currency, size=1, timeout=timeout)
            observation = lookup.latest_observation
        except OpenPricesError:
            observation = None
        if observation is not None:
            price_record = build_ingredient_price_from_observation(
                ingredient_id,
                observation,
                product_quantity=lookup.product.quantity,
                target_unit=target_unit,
                notes_prefix=_merge_notes(
                    notes_prefix,
                    "Ueber verknuepften Barcode gefunden",
                    f"Produkt: {lookup.product.name}",
                    f"Barcode: {barcode}",
                ),
            )
            price_record.year = year
            return OpenPricesImportResult(
                ingredient_id=ingredient_id,
                ingredient_name=ingredient_name,
                year=year,
                status="imported",
                message=f"{lookup.product.name} ({barcode})",
                query_used=f"Barcode {barcode}",
                matched_product_name=lookup.product.name,
                matched_product_code=barcode,
                matched_price=observation.price,
                matched_currency=observation.currency,
                matched_date=observation.date,
                price_record=price_record,
            )

    try:
        match = find_best_match_for_query(
            ingredient_name,
            target_unit=target_unit,
            currency=currency,
            timeout=timeout,
        )
    except OpenPricesError as exc:
        tried_queries = ", ".join(build_search_queries(ingredient_name))
        suggestions = suggest_matches_for_query(
            ingredient_name,
            target_unit=target_unit,
            currency=currency,
            timeout=timeout,
        )
        return OpenPricesImportResult(
            ingredient_id=ingredient_id,
            ingredient_name=ingredient_name,
            year=year,
            status="not_found",
            message=str(exc),
            query_used=tried_queries,
            suggestions=suggestions,
        )

    price_record = build_ingredient_price_from_observation(
        ingredient_id,
        match.observation,
        product_quantity=match.product.quantity,
        target_unit=target_unit,
        notes_prefix=_merge_notes(
            notes_prefix,
            f"Suchbegriff: {ingredient_name}",
            f"Produkt: {match.product.name}",
            f"Barcode: {match.product.code}",
        ),
    )
    price_record.year = year
    return OpenPricesImportResult(
        ingredient_id=ingredient_id,
        ingredient_name=ingredient_name,
        year=year,
        status="imported",
        message=f"{match.product.name} ({match.product.code})",
        query_used=match.query_used,
        matched_product_name=match.product.name,
        matched_product_code=match.product.code,
        matched_price=match.observation.price,
        matched_currency=match.observation.currency,
        matched_date=match.observation.date,
        price_record=price_record,
    )


def build_ingredient_price_from_suggestion(
    ingredient_id: int,
    suggestion: OpenPricesSuggestion,
    *,
    target_unit: str | None = None,
    notes_prefix: str | None = None,
) -> IngredientPrice:
    return build_ingredient_price_from_observation(
        ingredient_id,
        suggestion.observation,
        product_quantity=suggestion.product.quantity,
        target_unit=target_unit,
        notes_prefix=_merge_notes(
            notes_prefix,
            f"Suchbegriff: {suggestion.query_used}",
            f"Produkt: {suggestion.product.name}",
            f"Barcode: {suggestion.product.code}",
        ),
    )


def build_ingredient_price_from_observation(
    ingredient_id: int,
    observation: OpenPriceObservation,
    *,
    product_quantity: str | None = None,
    target_unit: str | None = None,
    notes_prefix: str | None = None,
) -> IngredientPrice:
    notes_parts = []
    if notes_prefix:
        notes_parts.append(notes_prefix.strip())
    if observation.location_name:
        notes_parts.append(f"Ort: {observation.location_name}")
    if observation.proof_type:
        notes_parts.append(f"Belegtyp: {observation.proof_type}")

    price_per_unit = observation.price
    unit = "Stk"

    parsed_quantity = parse_quantity_string(product_quantity)
    normalized_target_unit = price_service.normalize_unit(target_unit)
    if parsed_quantity is not None and normalized_target_unit is not None:
        package_amount, package_unit = parsed_quantity
        if price_service.can_convert_units(package_unit, normalized_target_unit):
            quantity_in_target_unit = price_service.convert_quantity(
                package_amount,
                from_unit=package_unit,
                to_unit=normalized_target_unit,
            )
            if quantity_in_target_unit > 0:
                price_per_unit = (observation.price / quantity_in_target_unit).quantize(Decimal("0.0001"))
                unit = unit_service.canonicalize_static(normalized_target_unit) or normalized_target_unit
                notes_parts.append(f"Umgerechnet aus Packung: {product_quantity}")
    elif product_quantity:
        notes_parts.append(f"Packung: {product_quantity}")

    return IngredientPrice(
        ingredient_id=ingredient_id,
        price_per_unit=price_per_unit,
        unit=unit,
        source="Open Prices",
        store=observation.store_name or observation.location_name,
        valid_from=observation.date,
        year=observation.date.year if observation.date else None,
        confidence="extern",
        notes=" | ".join(part for part in notes_parts if part) or None,
    )


def _get_json(path: str, *, params: dict[str, Any] | None = None, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    url = f"{API_BASE_URL}{path}{query}"
    try:
        with urlopen(url, timeout=timeout) as response:
            return json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            raise OpenPricesLookupError("Kein Produkt zu diesem Barcode gefunden.") from exc
        raise OpenPricesUnavailableError(f"Open Prices API Fehler: HTTP {exc.code}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise OpenPricesUnavailableError("Open Prices konnte nicht erreicht oder gelesen werden.") from exc


def _parse_product(payload: dict[str, Any]) -> OpenPricesProduct:
    quantity = None
    amount = payload.get("product_quantity")
    unit = payload.get("product_quantity_unit")
    if amount and unit:
        quantity = f"{amount} {unit}"
    elif amount:
        quantity = str(amount)

    return OpenPricesProduct(
        code=str(payload.get("code") or ""),
        name=str(payload.get("product_name") or payload.get("name") or "Unbekanntes Produkt"),
        quantity=quantity,
        price_count=int(payload.get("price_count") or 0),
        image_url=str(payload.get("image_url")) if payload.get("image_url") else None,
        brands=str(payload.get("brands")) if payload.get("brands") else None,
    )


def fetch_image_bytes(url: str, *, timeout: int = DEFAULT_TIMEOUT_SECONDS) -> bytes | None:
    """Laedt ein Vorschaubild fuer die Produktauswahl. Gibt bei jedem Fehler None zurueck - ein
    einzelnes fehlendes Thumbnail darf die Produktauswahl nie blockieren."""
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None


def parse_quantity_string(value: str | None) -> tuple[Decimal, str] | None:
    if not value:
        return None
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*([A-Za-zÃ„Ã–ÃœÃ¤Ã¶Ã¼]+)", value.strip())
    if match is None:
        return None

    amount = _parse_decimal(match.group(1).replace(",", "."))
    unit = price_service.normalize_unit(match.group(2))
    if amount is None or unit is None:
        return None
    if not price_service.can_convert_units(unit, unit):
        return None
    return (amount, unit)


# Open Prices ist ueberwiegend mit englischsprachigen Produktnamen befuellt (US/UK-lastiger
# Beitragsstamm) - generische deutsche Warenbegriffe wie "Apfel" oder "Zwiebel" treffen dort kaum
# Produkte mit hinterlegten Preisen, die englische Entsprechung dagegen deutlich mehr (siehe
# docs/... Recherche: "Apfel" 7137 Treffer/kaum mit Preis vs. "apple" 29515 Treffer, mehr mit
# Preisen). Deckt den tatsaechlichen Zutatenbestand der App ab, keine allgemeine Uebersetzung.
_GERMAN_TO_ENGLISH_FOOD_TERMS: dict[str, str] = {
    "apfel": "apple",
    "apfelmuss": "apple sauce",
    "aubergine": "eggplant",
    "banane": "banana",
    "basilikum": "basil",
    "birne": "pear",
    "blattspinat": "spinach",
    "bohnen": "beans",
    "brokkoli": "broccoli",
    "brot": "bread",
    "brotchen": "bread roll",
    "bruhe": "broth",
    "butter": "butter",
    "champignon": "mushroom",
    "champignons": "mushroom",
    "champingions": "mushroom",
    "cayennepfeffer": "cayenne pepper",
    "currypaste": "curry paste",
    "dill": "dill",
    "ei": "egg",
    "eier": "eggs",
    "eigelb": "egg yolk",
    "eiweiss": "egg white",
    "erbsen": "peas",
    "erdnusse": "peanuts",
    "essig": "vinegar",
    "essiggurken": "pickles",
    "feta": "feta cheese",
    "fond": "stock",
    "frischkase": "cream cheese",
    "gemusebruhe": "vegetable stock",
    "gouda": "gouda cheese",
    "gurke": "cucumber",
    "hackfleisch": "minced meat",
    "hartkase": "hard cheese",
    "honig": "honey",
    "joghurt": "yogurt",
    "karotte": "carrot",
    "kartoffel": "potato",
    "kartoffeln": "potatoes",
    "kase": "cheese",
    "ketchup": "ketchup",
    "kidneybohnen": "kidney beans",
    "knoblauch": "garlic",
    "kohl": "cabbage",
    "kokosmilch": "coconut milk",
    "kokusmilch": "coconut milk",
    "kopfsalat": "lettuce",
    "kreuzkummel": "cumin",
    "lauch": "leek",
    "limette": "lime",
    "limettensaft": "lime juice",
    "linsen": "lentils",
    "lorbeerblatt": "bay leaf",
    "mais": "corn",
    "majonaise": "mayonnaise",
    "majoran": "marjoram",
    "marmelade": "jam",
    "mehl": "flour",
    "milch": "milk",
    "muskat": "nutmeg",
    "nudeln": "pasta",
    "ol": "oil",
    "oliven": "olives",
    "olivenol": "olive oil",
    "paprika": "bell pepper",
    "petersilie": "parsley",
    "pfeffer": "pepper",
    "pinienkerne": "pine nuts",
    "puderzucker": "powdered sugar",
    "putenfleisch": "turkey",
    "radisschen": "radish",
    "reis": "rice",
    "rinderbruhe": "beef stock",
    "rinderfond": "beef stock",
    "rindfleisch": "beef",
    "rosinen": "raisins",
    "rotwein": "red wine",
    "rustzwiebeln": "fried onions",
    "sahne": "cream",
    "salat": "salad",
    "salz": "salt",
    "sauerkraut": "sauerkraut",
    "schalotte": "shallot",
    "schnittlauch": "chives",
    "schweinerippen": "pork ribs",
    "semmel": "bread roll",
    "semmelbrosel": "breadcrumbs",
    "senf": "mustard",
    "sojasauce": "soy sauce",
    "sojasosse": "soy sauce",
    "spagetti": "spaghetti",
    "speck": "bacon",
    "staudensellerie": "celery",
    "tofu": "tofu",
    "tomate": "tomato",
    "tomaten": "tomatoes",
    "tomatenmark": "tomato paste",
    "vanillezucker": "vanilla sugar",
    "wasser": "water",
    "weisskohl": "white cabbage",
    "weisswein": "white wine",
    "wurst": "sausage",
    "zitronensaft": "lemon juice",
    "zucchini": "zucchini",
    "zuchini": "zucchini",
    "zucker": "sugar",
    "zwiebel": "onion",
    "zwiebeln": "onions",
}


def build_search_queries(ingredient_name: str) -> list[str]:
    original = ingredient_name.strip()
    if not original:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        cleaned = value.strip()
        if not cleaned:
            return
        key = cleaned.lower()
        if key in seen:
            return
        seen.add(key)
        candidates.append(cleaned)

    add(original)

    collapsed = re.sub(r"\s+", " ", original.replace("&", " "))
    add(collapsed)

    normalized_tokens = normalize_name(original).split()
    if normalized_tokens:
        add(" ".join(normalized_tokens))

        singular_tokens = [_singularize_token(token) for token in normalized_tokens]
        add(" ".join(singular_tokens))

        without_fillers = [token for token in singular_tokens if token not in {"mit", "und", "a", "la"}]
        add(" ".join(without_fillers))

        # _singularize_token strippt Suffixe rein heuristisch und verstuemmelt dabei manche
        # bereits-singularen Woerter (z. B. "karotte" -> "karott"), darum bei der Uebersetzung
        # zusaetzlich gegen die unveraenderte normalisierte Form pruefen.
        kept_pairs = [
            (raw, singular)
            for raw, singular in zip(normalized_tokens, singular_tokens)
            if singular not in {"mit", "und", "a", "la"}
        ]
        if any(
            singular in _GERMAN_TO_ENGLISH_FOOD_TERMS or raw in _GERMAN_TO_ENGLISH_FOOD_TERMS
            for raw, singular in kept_pairs
        ):
            english_tokens = [
                _GERMAN_TO_ENGLISH_FOOD_TERMS.get(singular, _GERMAN_TO_ENGLISH_FOOD_TERMS.get(raw, singular))
                for raw, singular in kept_pairs
            ]
            add(" ".join(english_tokens))

    return candidates


def _parse_observation(payload: dict[str, Any]) -> OpenPriceObservation:
    price = _parse_decimal(payload.get("price"))
    if price is None:
        raise OpenPricesLookupError("Open Prices hat einen Preiseintrag ohne gültigen Preis geliefert.")

    location = payload.get("location") or {}
    proof = payload.get("proof") or {}

    return OpenPriceObservation(
        product_code=str(payload.get("product_code") or ""),
        product_name=str(payload.get("product_name") or ""),
        price=price,
        currency=str(payload.get("currency") or ""),
        date=_parse_date(payload.get("date")),
        store_name=_first_non_empty(
            location.get("osm_name"),
            location.get("osm_address_city"),
            location.get("osm_address_country"),
        ),
        location_name=_join_non_empty(
            location.get("osm_name"),
            location.get("osm_address_city"),
            location.get("osm_address_country"),
        ),
        proof_type=str(proof.get("type") or "") or None,
        price_is_discounted=bool(payload.get("price_is_discounted")),
    )


def _parse_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _first_non_empty(*values: Any) -> str | None:
    for value in values:
        if value:
            return str(value)
    return None


def _join_non_empty(*values: Any) -> str | None:
    parts = [str(value) for value in values if value]
    return ", ".join(parts) if parts else None


def _score_product_match(query: str, product: OpenPricesProduct, *, target_unit: str | None) -> float:
    normalized_query = normalize_name(query)
    normalized_name = normalize_name(product.name)
    if not normalized_name:
        return 0.0

    score = 0.0
    if normalized_name == normalized_query:
        score += 100.0
    elif normalized_query in normalized_name:
        score += 60.0

    query_tokens = set(normalized_query.split())
    name_tokens = set(normalized_name.split())
    if query_tokens:
        fuzzy_overlap = sum(_best_token_similarity(query_token, name_tokens) for query_token in query_tokens) / len(query_tokens)
        score += 40.0 * fuzzy_overlap

    if product.price_count > 0:
        score += min(product.price_count, 25)

    parsed_quantity = parse_quantity_string(product.quantity)
    normalized_target_unit = price_service.normalize_unit(target_unit)
    if parsed_quantity is not None and normalized_target_unit is not None:
        if price_service.can_convert_units(parsed_quantity[1], normalized_target_unit):
            score += 15.0
            quantity_in_target_unit = price_service.convert_quantity(
                parsed_quantity[0],
                from_unit=parsed_quantity[1],
                to_unit=normalized_target_unit,
            )
            score += min(float(quantity_in_target_unit), 2.0) * 5.0

    return score


def _merge_notes(*parts: str | None) -> str | None:
    joined = " | ".join(part.strip() for part in parts if part and part.strip())
    return joined or None


def _best_token_similarity(query_token: str, name_tokens: set[str]) -> float:
    if not name_tokens:
        return 0.0
    exact_or_prefix = [
        1.0
        for token in name_tokens
        if token == query_token or token.startswith(query_token) or query_token.startswith(token)
    ]
    if exact_or_prefix:
        return 1.0

    best = 0.0
    for token in name_tokens:
        shorter, longer = sorted((query_token, token), key=len)
        common_prefix_len = 0
        for left, right in zip(shorter, longer):
            if left != right:
                break
            common_prefix_len += 1
        best = max(best, common_prefix_len / max(len(longer), 1))
    return best


def _singularize_token(token: str) -> str:
    for suffix in ("nen", "en", "ern", "n", "e", "s"):
        if len(token) > len(suffix) + 3 and token.endswith(suffix):
            return token[: -len(suffix)]
    return token
