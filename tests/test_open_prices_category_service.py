from decimal import Decimal

from sqlalchemy import select

from app.db import session_scope
from app.models import Ingredient, OpenPricesCategory
from app.services import open_prices_category_service


def test_sync_categories_stores_taxonomy_entries(session_factory) -> None:
    taxonomy = {
        "en:apples": {
            "name": {"de": "Aepfel", "en": "Apples"},
            "parents": ["en:fruits"],
            "synonyms": {"de": ["Apfel"]},
        }
    }

    with session_scope(session_factory) as session:
        changed = open_prices_category_service.sync_categories(session, taxonomy)

    assert changed == 1
    with session_scope(session_factory) as session:
        category = session.get(OpenPricesCategory, "en:apples")
        assert category is not None
        assert category.name_de == "Aepfel"
        assert "en:fruits" in (category.parents_json or "")


def test_suggest_profiles_for_all_uses_curated_mapping(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Apfel", normalized_name="apfel", default_unit="kg"))
        session.add(Ingredient(name="Hinweis", normalized_name="hinweis"))

    with session_scope(session_factory) as session:
        suggested, skipped = open_prices_category_service.suggest_profiles_for_all(session)

    assert suggested == 1
    assert skipped == 1
    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient).where(Ingredient.normalized_name == "apfel")).scalar_one()
        assert ingredient.price_profile is not None
        assert ingredient.price_profile.category_tag == "en:apples"
        assert ingredient.price_profile.status == "suggested"


def test_find_product_candidates_filters_prices_to_germany(session_factory, monkeypatch) -> None:
    with session_scope(session_factory) as session:
        category = OpenPricesCategory(tag="en:apples", name_de="Aepfel")
        ingredient = Ingredient(name="Apfel", normalized_name="apfel", default_unit="kg")
        session.add_all([category, ingredient])
        session.flush()
        suggestion = open_prices_category_service.CategorySuggestion(
            tag="en:apples",
            name_de="Aepfel",
            name_en="Apples",
            confidence="hoch",
            reason="test",
            search_terms=["Apfel"],
        )
        profile = open_prices_category_service.create_or_update_profile_from_suggestion(session, ingredient, suggestion)
        session.flush()
        profile_id = profile.id

    payload = {
        "items": [
            {
                "product_code": "4316268599672",
                "product": {
                    "code": "4316268599672",
                    "product_name": "Tafelaepfel",
                    "brands": "Ein Herz fuer Erzeuger",
                    "product_quantity": 2000,
                    "product_quantity_unit": "g",
                    "image_url": "https://example.invalid/apple.jpg",
                    "price_count": 4,
                },
                "price": "2.49",
                "currency": "EUR",
                "date": "2026-07-14",
                "location": {"osm_name": "Netto City", "osm_address_country_code": "DE"},
            },
            {
                "product_code": "3250399883389",
                "product": {"code": "3250399883389", "product_name": "Pomme", "price_count": 10},
                "price": "2.59",
                "currency": "EUR",
                "date": "2026-07-04",
                "location": {"osm_name": "Intermarche", "osm_address_country_code": "FR"},
            },
        ]
    }

    def fake_get_json(path, *, params=None, timeout=15):
        assert path == "/prices"
        assert params["product__categories_tags__contains"] == "en:apples"
        return payload

    monkeypatch.setattr(open_prices_category_service.open_prices_service, "_get_json", fake_get_json)

    with session_scope(session_factory) as session:
        profile = session.get(open_prices_category_service.IngredientPriceProfile, profile_id)
        candidates = open_prices_category_service.find_product_candidates_for_profile(profile)

    assert len(candidates) == 1
    assert candidates[0].product_code == "4316268599672"
    assert candidates[0].price == Decimal("2.49")
    assert candidates[0].country_code == "DE"


def test_search_and_update_profile_category(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(OpenPricesCategory(tag="en:apple-compotes", name_de="Apfelkompotte", name_en="Apple compotes"))
        ingredient = Ingredient(name="Apfelmuss", normalized_name="apfelmuss", default_unit="kg")
        session.add(ingredient)
        session.flush()
        suggestion = open_prices_category_service.CategorySuggestion(
            tag="en:apple-sauces",
            name_de=None,
            name_en="Apple sauces",
            confidence="hoch",
            reason="test",
            search_terms=["Apfelmuss"],
        )
        profile = open_prices_category_service.create_or_update_profile_from_suggestion(session, ingredient, suggestion)

        matches = open_prices_category_service.search_categories(session, "Apfelkompott")
        assert [match.tag for match in matches] == ["en:apple-compotes"]

        open_prices_category_service.update_profile_category(
            profile,
            category_tag="en:apple-compotes",
            search_terms="Apfelmuss; Apfelmus",
            confirm=True,
        )

    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient).where(Ingredient.normalized_name == "apfelmuss")).scalar_one()
        assert ingredient.price_profile is not None
        assert ingredient.price_profile.category_tag == "en:apple-compotes"
        assert ingredient.price_profile.status == "confirmed"
        assert ingredient.price_profile.confidence == "manuell"
