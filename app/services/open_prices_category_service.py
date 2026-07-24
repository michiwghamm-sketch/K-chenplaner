from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import Ingredient, IngredientPriceProfile, OpenPricesCategory
from app.services import open_prices_service
from app.utils.normalization import normalize_name

CATEGORY_TAXONOMY_URL = "https://static.openfoodfacts.org/data/taxonomies/categories.json"
DEFAULT_USER_AGENT = "ZelaKueche/0.1"

PROFILE_STATUS_SUGGESTED = "suggested"
PROFILE_STATUS_CONFIRMED = "confirmed"
PROFILE_STATUS_NEEDS_REVIEW = "needs_review"

LOOKUP_MODE_CATEGORY = "category"
LOOKUP_MODE_BARCODE = "barcode"


CURATED_CATEGORY_TAGS: dict[str, str] = {
    "altmeisteressig": "en:vinegars",
    "apfel": "en:apples",
    "apfelmuss": "en:apple-compotes",
    "aubergine": "en:eggplants",
    "aufstrich": "en:spreads",
    "aufstriche verschieden": "en:spreads",
    "baguette": "en:baguettes",
    "balsamico": "en:balsamic-vinegars",
    "banane": "en:bananas",
    "basilikum": "en:basil",
    "basilikum tk": "en:basil",
    "basilikumessig": "en:vinegars",
    "blattsalat": "en:lettuces",
    "blattspinat": "en:spinaches",
    "brokkoli": "en:broccoli",
    "brot": "en:breads",
    "brotchen": "en:bread-rolls",
    "burgerbrotchen": "en:hamburger-buns",
    "butter": "en:butters",
    "butter aro": "en:butters",
    "butterschmalz": "en:clarified-butters",
    "cayennepfeffer": "en:cayenne-peppers",
    "champigons": "en:fresh-mushrooms",
    "champingions": "en:fresh-mushrooms",
    "chilli": "en:chili-peppers",
    "choco chips edeka": "en:chocolate-chips",
    "couscous": "en:couscous",
    "creme fraiche": "en:cremes-fraiches",
    "currrypaste": "en:curry-pastes",
    "currypaste rot": "en:curry-pastes",
    "dill": "en:dills",
    "ei": "en:eggs",
    "eier": "en:eggs",
    "eiwei": "en:egg-whites",
    "eigelb": "en:egg-yolks",
    "eiweiss": "en:egg-whites",
    "emsrind rindfleisch fur burger": "en:beef",
    "emsrind rindfleisch f r burger": "en:beef",
    "erpsen": "en:peas",
    "erpsen tk": "en:frozen-vegetables",
    "essig": "en:vinegars",
    "essiggurken": "en:pickles",
    "feta": "en:feta",
    "feta kase": "en:feta",
    "frischkase": "en:cream-cheeses",
    "frischkase verschieden": "en:cream-cheeses",
    "gekochte eier": "en:eggs",
    "gemischtes hackfleisch": "en:ground-meats",
    "gemusebruhe": "en:vegetable-broths",
    "gesalzene erdnusse gehack": "en:peanuts",
    "gnocchi": "en:gnocchi",
    "gouda mittelalt gerieben": "en:goudas",
    "gurke": "en:cucumbers",
    "hackfleisch": "en:ground-meats",
    "hackfleisch 75 rind 25 schwein": "en:ground-meats",
    "hartkase": "en:cheeses",
    "hochland schmelzkase cheddar": "en:processed-cheeses",
    "honeypops": "en:breakfast-cereals",
    "honig": "en:honeys",
    "honig aro": "en:honeys",
    "joghurt": "en:yogurts",
    "kaba pulver": "en:cocoa-powders",
    "karotte": "en:carrots",
    "kartoffel mehlig": "en:potatoes",
    "kartoffelbreiulver": "en:instant-mashed-potatoes",
    "kartoffeln": "en:potatoes",
    "kartoffeln festkochend": "en:potatoes",
    "kase": "en:cheeses",
    "kase gerieben": "en:grated-cheeses",
    "ketchup": "en:tomato-ketchup",
    "kidneybohnen": "en:kidney-beans",
    "kirschtomaten": "en:cherry-tomatoes",
    "knoblauch": "en:garlic",
    "kokusmilch": "en:coconut-milks",
    "kopfsalat": "en:lettuces",
    "kreuzkummel": "en:cumin",
    "lasagne platten": "en:lasagne-sheets",
    "lauch": "en:leeks",
    "limettensaft": "en:lime-juices",
    "lorbeerblatt": "en:bay-leaves",
    "mais": "en:corn",
    "majonaise": "en:mayonnaises",
    "majoran": "en:marjoram",
    "marmelade": "en:jams",
    "mehl": "en:wheat-flour-t405",
    "mehl 550": "en:wheat-flour-type-55-for-bread",
    "milch": "en:milks",
    "milch laktosefrei": "en:lactose-free-milks",
    "mozarelle trocken": "en:mozzarella",
    "muskat": "en:nutmeg",
    "nudeln": "en:durum-wheat-pasta",
    "nutella": "en:hazelnut-spreads",
    "ol": "en:plant-based-oils",
    "olivenol": "en:olive-oils",
    "oregano": "en:oregano",
    "paprika": "en:sweet-peppers",
    "paprika rot": "en:sweet-peppers",
    "paprika rot gelb": "en:sweet-peppers",
    "paprika pulver": "en:paprika",
    "paprika pulver gerauchert": "en:paprika",
    "paprika edelsu": "en:paprika",
    "paprika edels": "en:paprika",
    "paprika edelsuss": "en:paprika",
    "paprika rosenscharf": "en:paprika",
    "paprikagewurze": "en:paprika",
    "petersilie": "en:parsley",
    "petersilie frisch": "en:parsley",
    "pfeffer": "en:peppers",
    "pinienkerne": "en:pine-nuts",
    "puderzucker": "en:powdered-sugars",
    "putenfleisch": "en:turkey-meats",
    "radisschen": "en:radishes",
    "re": "en:rices",
    "reis": "en:rices",
    "reis jasmin": "en:jasmine-rices",
    "rinder hackfleisch": "en:fresh-ground-beef-preparations",
    "rinderbruhe": "en:beef-broth",
    "rinderfond": "en:beef-broth",
    "rindergulasch": "en:beef",
    "rinderschulter": "en:beef",
    "rosinen": "en:raisins",
    "rotwein": "en:red-wines",
    "rostzwiebeln": "en:fried-onions",
    "sahne": "en:whipped-creams",
    "sahne laktosefrei": "en:whipped-creams",
    "salat": "en:lettuces",
    "salz": "en:salts",
    "sauerkraut": "en:sauerkrauts",
    "schalotte": "en:shallots",
    "schnittlauch": "en:chives",
    "schokocreme dm": "en:chocolate-spreads",
    "schweine hackfleisch": "en:ground-meats",
    "schweinerippen": "en:pork-ribs",
    "semmel": "en:bread-rolls",
    "semmelbrosel": "en:breadcrumbs",
    "semmelknodelbrot": "en:bread-rolls",
    "semmelwurfel getrocknet": "en:croutons",
    "senf": "en:mustards",
    "sojasaucce": "en:soy-sauces",
    "sojasaue hell": "en:soy-sauces",
    "sojasau e hell": "en:soy-sauces",
    "sojasause hell": "en:soy-sauces",
    "sojasoe": "en:soy-sauces",
    "sojaso e": "en:soy-sauces",
    "sojasosse": "en:soy-sauces",
    "spagetti": "en:spaghetti",
    "speck": "en:bacon",
    "staudensellerie": "en:celery",
    "tofu hack": "en:tofu",
    "tomaten": "en:tomatoes",
    "tomaten geschalt": "en:canned-tomatoes",
    "tomaten passiert": "en:strained-tomatoes",
    "tomaten passiert dose": "en:strained-tomatoes",
    "tomatenmark": "en:tomato-pastes",
    "tortelini": "en:tortellini",
    "vanillezucker": "en:vanilla-sugars",
    "wasser": "en:waters",
    "wasser rum": "en:waters",
    "weisskohl": "en:white-cabbages",
    "weisswein": "en:white-wines",
    "weikohl": "en:white-cabbages",
    "weiwein": "en:white-wines",
    "wei kohl": "en:white-cabbages",
    "wei wein": "en:white-wines",
    "wiener": "en:pork-sausages",
    "wurst": "en:sausages",
    "wurziger kase": "en:cheeses",
    "zitronensaft": "en:lemon-juices",
    "zuchini": "en:zucchini",
    "zucker": "en:sugars",
    "zwiebel": "en:onions",
    "braune linsen": "en:lentils",
    "getrocknete tomaten": "en:sun-dried-tomatoes",
}

NON_INGREDIENT_NAMES = {
    "gnocchi salat",
    "hinweis",
    "letzte pflege",
    "rahmgulasch mit sk",
}


@dataclass(slots=True)
class CategorySuggestion:
    tag: str
    name_de: str | None
    name_en: str | None
    confidence: str
    reason: str
    search_terms: list[str]


@dataclass(slots=True)
class ProductCandidate:
    product_code: str
    product_name: str
    brands: str | None
    quantity: str | None
    image_url: str | None
    price: Decimal
    currency: str
    price_date: date | None
    store_name: str | None
    country_code: str | None
    price_count: int


def fetch_category_taxonomy(*, timeout: int = 60) -> dict[str, Any]:
    request = Request(
        CATEGORY_TAXONOMY_URL,
        headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise open_prices_service.OpenPricesUnavailableError("Open-Food-Facts-Kategorien konnten nicht geladen werden.") from exc


def sync_categories(session: Session, taxonomy: dict[str, Any] | None = None) -> int:
    taxonomy = taxonomy or fetch_category_taxonomy()
    changed = 0
    for tag, payload in taxonomy.items():
        if not isinstance(payload, dict):
            continue
        names = payload.get("name") or {}
        if not isinstance(names, dict):
            names = {}
        category = session.get(OpenPricesCategory, tag)
        if category is None:
            category = OpenPricesCategory(tag=tag)
            session.add(category)
        category.name_de = _string_or_none(names.get("de"))
        category.name_en = _string_or_none(names.get("en"))
        category.parents_json = json.dumps(payload.get("parents") or [], ensure_ascii=False)
        category.synonyms_json = json.dumps(payload.get("synonyms") or {}, ensure_ascii=False)
        category.raw_json = json.dumps(payload, ensure_ascii=False)
        changed += 1
    return changed


def ensure_curated_categories(session: Session) -> int:
    """Legt kleine Platzhalter fuer kuratierte Tags an, falls die Taxonomie noch nicht synchronisiert wurde."""
    created = 0
    for tag in sorted(set(CURATED_CATEGORY_TAGS.values())):
        if session.get(OpenPricesCategory, tag) is not None:
            continue
        session.add(OpenPricesCategory(tag=tag, name_en=_tag_to_label(tag)))
        created += 1
    return created


def suggest_category_for_ingredient(session: Session, ingredient: Ingredient) -> CategorySuggestion | None:
    normalized = _normalize_ingredient_key(ingredient.name)
    if normalized in NON_INGREDIENT_NAMES:
        return None
    tag = CURATED_CATEGORY_TAGS.get(normalized)
    if tag is None:
        return None
    category = session.get(OpenPricesCategory, tag)
    return CategorySuggestion(
        tag=tag,
        name_de=category.name_de if category else None,
        name_en=(category.name_en if category else None) or _tag_to_label(tag),
        confidence="hoch",
        reason="kuratierte Zutatenliste",
        search_terms=build_search_terms(ingredient.name),
    )


def create_or_update_profile_from_suggestion(
    session: Session,
    ingredient: Ingredient,
    suggestion: CategorySuggestion,
    *,
    overwrite_confirmed: bool = False,
) -> IngredientPriceProfile:
    profile = ingredient.price_profile
    if profile is None:
        profile = IngredientPriceProfile(ingredient=ingredient)
        session.add(profile)
    if profile.status == PROFILE_STATUS_CONFIRMED and not overwrite_confirmed:
        return profile
    profile.category_tag = suggestion.tag
    profile.search_terms = "; ".join(suggestion.search_terms)
    profile.lookup_mode = LOOKUP_MODE_CATEGORY
    profile.status = PROFILE_STATUS_SUGGESTED
    profile.confidence = suggestion.confidence
    profile.notes = suggestion.reason
    return profile


def suggest_profiles_for_all(session: Session, *, overwrite_confirmed: bool = False) -> tuple[int, int]:
    ensure_curated_categories(session)
    ingredients = session.execute(select(Ingredient).where(Ingredient.active.is_(True)).order_by(Ingredient.name)).scalars().all()
    suggested = 0
    skipped = 0
    for ingredient in ingredients:
        suggestion = suggest_category_for_ingredient(session, ingredient)
        if suggestion is None:
            skipped += 1
            continue
        create_or_update_profile_from_suggestion(
            session,
            ingredient,
            suggestion,
            overwrite_confirmed=overwrite_confirmed,
        )
        suggested += 1
    return suggested, skipped


def confirm_profile(profile: IngredientPriceProfile) -> None:
    profile.status = PROFILE_STATUS_CONFIRMED


def update_profile_category(
    profile: IngredientPriceProfile,
    *,
    category_tag: str,
    search_terms: str | None = None,
    confirm: bool = False,
) -> None:
    profile.category_tag = category_tag
    if search_terms is not None:
        profile.search_terms = search_terms
    profile.lookup_mode = LOOKUP_MODE_CATEGORY
    profile.status = PROFILE_STATUS_CONFIRMED if confirm else PROFILE_STATUS_SUGGESTED
    profile.confidence = "manuell"
    profile.notes = "Kategorie manuell gesetzt"


def search_categories(session: Session, query: str, *, limit: int = 30) -> list[OpenPricesCategory]:
    normalized_query = query.strip()
    if not normalized_query:
        return []
    like = f"%{normalized_query}%"
    return (
        session.execute(
            select(OpenPricesCategory)
            .where(
                or_(
                    OpenPricesCategory.tag.ilike(like),
                    OpenPricesCategory.name_de.ilike(like),
                    OpenPricesCategory.name_en.ilike(like),
                )
            )
            .order_by(OpenPricesCategory.name_de, OpenPricesCategory.name_en, OpenPricesCategory.tag)
            .limit(limit)
        )
        .scalars()
        .all()
    )


def assign_product_to_ingredient(ingredient: Ingredient, candidate: ProductCandidate) -> None:
    ingredient.barcode = candidate.product_code
    brand_text = f" ({candidate.brands})" if candidate.brands else ""
    quantity_text = f", {candidate.quantity}" if candidate.quantity else ""
    ingredient.barcode_product_label = f"{candidate.product_name}{brand_text}{quantity_text}"
    if ingredient.price_profile is not None:
        ingredient.price_profile.lookup_mode = LOOKUP_MODE_BARCODE
        ingredient.price_profile.status = PROFILE_STATUS_CONFIRMED


def build_search_terms(ingredient_name: str) -> list[str]:
    terms = open_prices_service.build_search_queries(ingredient_name)
    normalized = normalize_name(ingredient_name)
    translated = open_prices_service._GERMAN_TO_ENGLISH_FOOD_TERMS.get(normalized)  # noqa: SLF001 - existing local map
    if translated and translated not in terms:
        terms.append(translated)
    return terms


def find_product_candidates_for_profile(
    profile: IngredientPriceProfile,
    *,
    country_code: str = "DE",
    currency: str = "EUR",
    size: int = 80,
    pages: int = 3,
    timeout: int = open_prices_service.DEFAULT_TIMEOUT_SECONDS,
) -> list[ProductCandidate]:
    if not profile.category_tag:
        return []
    candidates: dict[str, ProductCandidate] = {}
    for page in range(1, pages + 1):
        payload = open_prices_service._get_json(  # noqa: SLF001 - shared API helper keeps error handling consistent
            "/prices",
            params={
                "type": "PRODUCT",
                "product__categories_tags__contains": profile.category_tag,
                "currency": currency,
                "order_by": "-date",
                "size": size,
                "page": page,
            },
            timeout=timeout,
        )
        items = payload.get("items", [])
        if not items:
            break
        for item in items:
            location = item.get("location") or {}
            if country_code and location.get("osm_address_country_code") != country_code:
                continue
            product = item.get("product") or {}
            product_code = str(item.get("product_code") or product.get("code") or "")
            if not product_code or product_code in candidates:
                continue
            price = _decimal_or_none(item.get("price"))
            if price is None:
                continue
            candidates[product_code] = ProductCandidate(
                product_code=product_code,
                product_name=str(product.get("product_name") or item.get("product_name") or "Unbekanntes Produkt"),
                brands=_string_or_none(product.get("brands")),
                quantity=_product_quantity(product),
                image_url=_string_or_none(product.get("image_url")),
                price=price,
                currency=str(item.get("currency") or currency),
                price_date=_date_or_none(item.get("date")),
                store_name=_string_or_none(location.get("osm_name")),
                country_code=_string_or_none(location.get("osm_address_country_code")),
                price_count=int(product.get("price_count") or 0),
            )
    return sorted(candidates.values(), key=lambda candidate: (candidate.price_count, candidate.price_date or date.min), reverse=True)


def _normalize_ingredient_key(value: str) -> str:
    normalized = normalize_name(value)
    normalized = normalized.replace(" tk", "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _tag_to_label(tag: str) -> str:
    return tag.split(":", 1)[-1].replace("-", " ")


def _product_quantity(product: dict[str, Any]) -> str | None:
    amount = product.get("product_quantity")
    unit = product.get("product_quantity_unit")
    if amount and unit:
        return f"{amount} {unit}"
    if product.get("quantity"):
        return str(product.get("quantity"))
    if amount:
        return str(amount)
    return None


def _string_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _date_or_none(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None
