from decimal import Decimal

import pytest

from app.db import session_scope
from app.models import Ingredient, Recipe, RecipeIngredient
from app.services import recipe_service


def test_add_ingredient_to_recipe_rejects_incompatible_unit(session_factory) -> None:
    """Wiener werden stueckweise gefuehrt - 'kg' ist eine andere Einheitenart (Stk hat bewusst
    keinen Umrechnungsfaktor zu Masse, da die Groesse eines Stuecks je Zutat stark schwankt) und
    muss abgelehnt werden, statt die Standardeinheit stillschweigend zu ueberschreiben."""
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Wiener", normalized_name="wiener", default_unit="Stk")
        session.add_all([recipe, ingredient])
        session.flush()

        with pytest.raises(ValueError, match="passt nicht"):
            recipe_service.add_ingredient_to_recipe(
                session, recipe, ingredient_id=ingredient.id, quantity=Decimal("1.000"), unit="kg"
            )


def test_add_ingredient_to_recipe_allows_kitchen_measure_units_compatible_with_mass(session_factory) -> None:
    """Zehe/EL/TL/Prise/Bund/Scheibe sind ueber feste Grammnaeherungen mit g/kg umrechenbar (siehe
    price_service.UNIT_FACTORS), damit Rezepte kuechenuebliche Einheiten verwenden koennen, waehrend
    der Einkaufspreis in kg gepflegt wird."""
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Knoblauch", normalized_name="knoblauch", default_unit="kg")
        session.add_all([recipe, ingredient])
        session.flush()

        link = recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("2.000"), unit="Zehe"
        )
        assert link.unit == "Zehe"


def test_add_ingredient_to_recipe_allows_compatible_mass_unit(session_factory) -> None:
    """kg/g gehoeren zur selben Einheitenart (Masse) - das ist der uebliche 'in kg eingekauft, im
    Rezept in g verwendet'-Fall und muss weiterhin erlaubt sein."""
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Mehl", normalized_name="mehl", default_unit="kg")
        session.add_all([recipe, ingredient])
        session.flush()

        link = recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("250.000"), unit="g"
        )
        assert link.unit == "g"


def test_add_ingredient_to_recipe_sets_missing_default_unit_from_recipe_unit(session_factory) -> None:
    """Eine frisch angelegte Zutat ohne Standardeinheit bekommt beim ersten Rezepteinsatz die dort
    gewaehlte Einheit als neue Standardeinheit - kein separater Pflichtschritt noetig."""
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Neue Zutat", normalized_name="neue zutat")
        session.add_all([recipe, ingredient])
        session.flush()

        recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("1.000"), unit="Bund"
        )
        assert ingredient.default_unit == "Bund"


def test_add_ingredient_to_recipe_rejects_unit_not_in_pool(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Mehl", normalized_name="mehl", default_unit="kg")
        session.add_all([recipe, ingredient])
        session.flush()

        with pytest.raises(ValueError):
            recipe_service.add_ingredient_to_recipe(
                session, recipe, ingredient_id=ingredient.id, quantity=Decimal("1.000"), unit="Krug"
            )


def test_update_ingredient_quantity_rejects_incompatible_unit(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht")
        ingredient = Ingredient(name="Wiener", normalized_name="wiener", default_unit="Stk")
        session.add_all([recipe, ingredient])
        session.flush()
        link = recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=ingredient.id, quantity=Decimal("2.000"), unit="Stk"
        )
        session.flush()
        link_id = link.id

    with session_scope(session_factory) as session:
        recipe = session.query(Recipe).one()
        link = session.get(RecipeIngredient, link_id)
        with pytest.raises(ValueError, match="passt nicht"):
            recipe_service.update_ingredient_quantity(session, recipe, link, quantity=Decimal("1.000"), unit="kg")
