from __future__ import annotations

from datetime import date
from decimal import Decimal
from urllib.error import HTTPError

import pytest

from app.services import open_prices_service


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, *_args, **_kwargs) -> bytes:
        import json

        return json.dumps(self.payload).encode("utf-8")


def test_lookup_product_prices_reads_product_and_latest_observations(monkeypatch) -> None:
    payloads = {
        "https://prices.openfoodfacts.org/api/v1/products/code/3017620422003": {
            "code": "3017620422003",
            "product_name": "Nutella",
            "product_quantity": 400,
            "product_quantity_unit": "g",
            "price_count": 159,
        },
        "https://prices.openfoodfacts.org/api/v1/prices?product_code=3017620422003&order_by=-date&size=2&currency=EUR": {
            "items": [
                {
                    "product_code": "3017620422003",
                    "product_name": "Nutella",
                    "price": 2.77,
                    "currency": "EUR",
                    "date": "2026-06-12",
                    "price_is_discounted": False,
                    "location": {
                        "osm_name": "Auchan Supermarche",
                        "osm_address_city": "Grenoble",
                        "osm_address_country": "Frankreich",
                    },
                    "proof": {"type": "PRICE_TAG"},
                },
                {
                    "product_code": "3017620422003",
                    "product_name": "Nutella",
                    "price": 2.99,
                    "currency": "EUR",
                    "date": "2026-05-01",
                    "price_is_discounted": True,
                    "location": {"osm_name": "Carrefour"},
                    "proof": {"type": "RECEIPT"},
                },
            ]
        },
    }

    def fake_urlopen(url: str, timeout: int = 15):
        assert timeout == 15
        return _FakeResponse(payloads[url])

    monkeypatch.setattr(open_prices_service, "urlopen", fake_urlopen)

    result = open_prices_service.lookup_product_prices("3017620422003", size=2)

    assert result.product.name == "Nutella"
    assert result.product.quantity == "400 g"
    assert result.latest_observation is not None
    assert result.latest_observation.price == Decimal("2.77")
    assert result.latest_observation.currency == "EUR"
    assert result.latest_observation.date == date(2026, 6, 12)
    assert result.latest_observation.store_name == "Auchan Supermarche"


def test_build_ingredient_price_from_observation_maps_external_metadata() -> None:
    observation = open_prices_service.OpenPriceObservation(
        product_code="3017620422003",
        product_name="Nutella",
        price=Decimal("2.77"),
        currency="EUR",
        date=date(2026, 6, 12),
        store_name="Auchan Supermarche",
        location_name="Auchan Supermarche, Grenoble, Frankreich",
        proof_type="PRICE_TAG",
        price_is_discounted=False,
    )

    price = open_prices_service.build_ingredient_price_from_observation(
        5,
        observation,
        product_quantity="400 g",
        target_unit="kg",
        notes_prefix="Barcode-Import",
    )

    assert price.ingredient_id == 5
    assert price.price_per_unit == Decimal("6.9250")
    assert price.unit == "kg"
    assert price.source == "Open Prices"
    assert price.store == "Auchan Supermarche"
    assert price.valid_from == date(2026, 6, 12)
    assert price.year == 2026
    assert "Barcode-Import" in (price.notes or "")
    assert "Grenoble" in (price.notes or "")
    assert "Packung" in (price.notes or "")


def test_lookup_product_prices_raises_lookup_error_for_missing_product(monkeypatch) -> None:
    def fake_urlopen(url: str, timeout: int = 15):
        raise HTTPError(url, 404, "Not found", hdrs=None, fp=None)

    monkeypatch.setattr(open_prices_service, "urlopen", fake_urlopen)

    with pytest.raises(open_prices_service.OpenPricesLookupError):
        open_prices_service.lookup_product_prices("0000000000000")


def test_parse_quantity_string_handles_simple_amounts() -> None:
    assert open_prices_service.parse_quantity_string("400 g") == (Decimal("400"), "g")


def test_find_best_match_for_query_prefers_more_relevant_product(monkeypatch) -> None:
    def fake_search_products(query: str, *, size: int = 10, timeout: int = 15):
        return [
            open_prices_service.OpenPricesProduct(code="1", name="Zwiebel schmalz", quantity="200 g", price_count=4),
            open_prices_service.OpenPricesProduct(code="2", name="Rote Zwiebeln", quantity="1 kg", price_count=9),
        ]

    def fake_lookup_product_prices(barcode: str, *, size: int = 10, currency: str | None = "EUR", timeout: int = 15):
        product_name = "Zwiebel schmalz" if barcode == "1" else "Rote Zwiebeln"
        quantity = "200 g" if barcode == "1" else "1 kg"
        product = open_prices_service.OpenPricesProduct(code=barcode, name=product_name, quantity=quantity, price_count=4)
        observation = open_prices_service.OpenPriceObservation(
            product_code=barcode,
            product_name=product_name,
            price=Decimal("2.50"),
            currency="EUR",
            date=date(2026, 7, 1),
            store_name="Testmarkt",
            location_name="Testmarkt, Regensburg, Deutschland",
            proof_type="PRICE_TAG",
            price_is_discounted=False,
        )
        return open_prices_service.OpenPricesLookupResult(product=product, observations=[observation])

    monkeypatch.setattr(open_prices_service, "search_products", fake_search_products)
    monkeypatch.setattr(open_prices_service, "lookup_product_prices", fake_lookup_product_prices)

    match = open_prices_service.find_best_match_for_query("Zwiebel", target_unit="kg")

    assert match.product.code == "2"
    assert match.product.name == "Rote Zwiebeln"
    assert match.query_used == "Zwiebel"


def test_import_price_for_ingredient_returns_price_record(monkeypatch) -> None:
    observation = open_prices_service.OpenPriceObservation(
        product_code="123",
        product_name="Nudeln",
        price=Decimal("1.20"),
        currency="EUR",
        date=date(2026, 7, 1),
        store_name="Testmarkt",
        location_name="Testmarkt, Regensburg, Deutschland",
        proof_type="PRICE_TAG",
        price_is_discounted=False,
    )
    match = open_prices_service.OpenPricesSearchMatch(
        product=open_prices_service.OpenPricesProduct(code="123", name="Nudeln", quantity="500 g", price_count=5),
        observation=observation,
        score=123.0,
        query_used="Nudeln",
    )

    monkeypatch.setattr(open_prices_service, "find_best_match_for_query", lambda *args, **kwargs: match)

    result = open_prices_service.import_price_for_ingredient(
        7,
        "Nudeln",
        target_unit="kg",
        year=2026,
    )

    assert result.status == "imported"
    assert result.price_record is not None
    assert result.price_record.ingredient_id == 7
    assert result.price_record.price_per_unit == Decimal("2.4000")
    assert "Suchbegriff: Nudeln" in (result.price_record.notes or "")
    assert result.query_used == "Nudeln"
    assert result.matched_product_name == "Nudeln"
    assert result.matched_date == date(2026, 7, 1)


def test_lookup_product_prices_parses_image_url_and_brands(monkeypatch) -> None:
    payloads = {
        "https://prices.openfoodfacts.org/api/v1/products/code/3478822005249": {
            "code": "3478822005249",
            "product_name": "Ketchup",
            "brands": "Jardin bio",
            "image_url": "https://images.openfoodfacts.org/images/products/347/882/200/5249/front_fr.49.400.jpg",
            "product_quantity": 560,
            "product_quantity_unit": "g",
            "price_count": 6,
        },
        "https://prices.openfoodfacts.org/api/v1/prices?product_code=3478822005249&order_by=-date&size=1&currency=EUR": {
            "items": []
        },
    }

    def fake_urlopen(url: str, timeout: int = 15):
        return _FakeResponse(payloads[url])

    monkeypatch.setattr(open_prices_service, "urlopen", fake_urlopen)

    result = open_prices_service.lookup_product_prices("3478822005249", size=1)

    assert result.product.brands == "Jardin bio"
    assert result.product.image_url == "https://images.openfoodfacts.org/images/products/347/882/200/5249/front_fr.49.400.jpg"


def test_fetch_image_bytes_returns_none_on_error(monkeypatch) -> None:
    from urllib.error import URLError

    def fake_urlopen(url: str, timeout: int = 15):
        raise URLError("kein Netz")

    monkeypatch.setattr(open_prices_service, "urlopen", fake_urlopen)

    assert open_prices_service.fetch_image_bytes("https://example.invalid/x.jpg") is None


def test_fetch_image_bytes_returns_bytes_on_success(monkeypatch) -> None:
    class _FakeImageResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b"\x89PNG..."

    monkeypatch.setattr(open_prices_service, "urlopen", lambda url, timeout=15: _FakeImageResponse())

    assert open_prices_service.fetch_image_bytes("https://example.invalid/x.jpg") == b"\x89PNG..."


def test_import_price_for_ingredient_prefers_linked_barcode_over_name_search(monkeypatch) -> None:
    observation = open_prices_service.OpenPriceObservation(
        product_code="123",
        product_name="Ketchup Jardin bio",
        price=Decimal("1.99"),
        currency="EUR",
        date=date(2026, 7, 1),
        store_name="Testmarkt",
        location_name="Testmarkt, Regensburg, Deutschland",
        proof_type="PRICE_TAG",
        price_is_discounted=False,
    )
    lookup_result = open_prices_service.OpenPricesLookupResult(
        product=open_prices_service.OpenPricesProduct(code="123", name="Ketchup Jardin bio", quantity="560 g", price_count=6),
        observations=[observation],
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("find_best_match_for_query haette nicht aufgerufen werden duerfen")

    monkeypatch.setattr(open_prices_service, "lookup_product_prices", lambda *args, **kwargs: lookup_result)
    monkeypatch.setattr(open_prices_service, "find_best_match_for_query", fail_if_called)

    result = open_prices_service.import_price_for_ingredient(
        7,
        "Ketchup",
        target_unit="kg",
        year=2026,
        barcode="123",
    )

    assert result.status == "imported"
    assert result.matched_product_code == "123"
    assert result.query_used == "Barcode 123"
    assert result.price_record is not None


def test_import_price_for_ingredient_falls_back_to_name_search_when_barcode_lookup_fails(monkeypatch) -> None:
    match = open_prices_service.OpenPricesSearchMatch(
        product=open_prices_service.OpenPricesProduct(code="999", name="Ketchup", quantity="500 g", price_count=3),
        observation=open_prices_service.OpenPriceObservation(
            product_code="999",
            product_name="Ketchup",
            price=Decimal("1.50"),
            currency="EUR",
            date=date(2026, 7, 1),
            store_name="Testmarkt",
            location_name="Testmarkt, Regensburg, Deutschland",
            proof_type="PRICE_TAG",
            price_is_discounted=False,
        ),
        score=100.0,
        query_used="Ketchup",
    )

    def fake_lookup_product_prices(*args, **kwargs):
        raise open_prices_service.OpenPricesLookupError("kein Produkt zu diesem Barcode")

    monkeypatch.setattr(open_prices_service, "lookup_product_prices", fake_lookup_product_prices)
    monkeypatch.setattr(open_prices_service, "find_best_match_for_query", lambda *args, **kwargs: match)

    result = open_prices_service.import_price_for_ingredient(
        7,
        "Ketchup",
        target_unit="kg",
        year=2026,
        barcode="000000000000",
    )

    assert result.status == "imported"
    assert result.matched_product_code == "999"
    assert result.query_used == "Ketchup"


def test_build_search_queries_adds_normalized_and_singular_variants() -> None:
    queries = open_prices_service.build_search_queries("Gnocchi Salate")

    assert "Gnocchi Salate" in queries
    assert "gnocchi salat" in queries


def test_build_search_queries_adds_english_translation_for_known_terms() -> None:
    # Open Prices ist ueberwiegend englischsprachig befuellt - generische deutsche Begriffe wie
    # "Apfel" liefern dort kaum Treffer mit Preisdaten, die englische Entsprechung deutlich mehr.
    assert "apple" in open_prices_service.build_search_queries("Apfel")
    assert "onion" in open_prices_service.build_search_queries("Zwiebeln")


def test_build_search_queries_falls_back_to_raw_token_when_singularizer_overstrips() -> None:
    # _singularize_token strippt "karotte" (bereits Singular) faelschlich zu "karott" - die
    # Uebersetzung muss trotzdem greifen, indem sie zusaetzlich die unveraenderte Form prueft.
    assert "carrot" in open_prices_service.build_search_queries("Karotte")


def test_build_search_queries_skips_english_variant_for_unknown_terms() -> None:
    queries = open_prices_service.build_search_queries("Hinweis")
    assert len(queries) == len(set(q.lower() for q in queries))


def test_search_products_orders_by_price_count_descending_by_default(monkeypatch) -> None:
    payloads = {
        "https://prices.openfoodfacts.org/api/v1/products?product_name__like=Apfel&size=10&order_by=-price_count": {
            "items": [{"code": "1", "product_name": "Apfelmus", "price_count": 3}]
        },
    }

    def fake_urlopen(url: str, timeout: int = 15):
        return _FakeResponse(payloads[url])

    monkeypatch.setattr(open_prices_service, "urlopen", fake_urlopen)

    products = open_prices_service.search_products("Apfel")

    assert len(products) == 1
    assert products[0].name == "Apfelmus"


def test_suggest_matches_for_query_returns_ranked_suggestions(monkeypatch) -> None:
    def fake_search_products(query: str, *, size: int = 10, timeout: int = 15):
        return [
            open_prices_service.OpenPricesProduct(code="1", name="Zwiebel schmalz", quantity="200 g", price_count=4),
            open_prices_service.OpenPricesProduct(code="2", name="Rote Zwiebeln", quantity="1 kg", price_count=9),
        ]

    def fake_lookup_product_prices(barcode: str, *, size: int = 10, currency: str | None = "EUR", timeout: int = 15):
        product_name = "Zwiebel schmalz" if barcode == "1" else "Rote Zwiebeln"
        quantity = "200 g" if barcode == "1" else "1 kg"
        product = open_prices_service.OpenPricesProduct(code=barcode, name=product_name, quantity=quantity, price_count=4)
        observation = open_prices_service.OpenPriceObservation(
            product_code=barcode,
            product_name=product_name,
            price=Decimal("2.50"),
            currency="EUR",
            date=date(2026, 7, 1),
            store_name="Testmarkt",
            location_name="Testmarkt, Regensburg, Deutschland",
            proof_type="PRICE_TAG",
            price_is_discounted=False,
        )
        return open_prices_service.OpenPricesLookupResult(product=product, observations=[observation])

    monkeypatch.setattr(open_prices_service, "search_products", fake_search_products)
    monkeypatch.setattr(open_prices_service, "lookup_product_prices", fake_lookup_product_prices)

    suggestions = open_prices_service.suggest_matches_for_query("Zwiebel", target_unit="kg", limit=2)

    assert len(suggestions) == 2
    assert suggestions[0].product.name == "Rote Zwiebeln"
    assert suggestions[1].product.name == "Zwiebel schmalz"
