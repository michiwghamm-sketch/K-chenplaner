import pytest
from sqlalchemy import select

from app.db import session_scope
from app.models import Ingredient
from app.services import unit_service


def test_ensure_default_units_seeds_pool_and_is_idempotent(session_factory) -> None:
    with session_scope(session_factory) as session:
        names = unit_service.list_unit_names(session)
        assert "kg" in names
        assert "Stk" in names
        count_before = len(names)

        unit_service.ensure_default_units(session)
        assert len(unit_service.list_unit_names(session)) == count_before


def test_ensure_default_units_syncs_kind_for_existing_builtin_units(session_factory) -> None:
    """Regression: die 'kind'-Gruppierung mitgelieferter Einheiten kann sich aendern (z. B. wurde
    Zehe nachtraeglich der 'mass'-Gruppe zugeordnet) - ein erneuter Aufruf muss bereits vorhandene
    Zeilen synchron halten, nicht nur fehlende Einheiten ergaenzen."""
    with session_scope(session_factory) as session:
        unit = unit_service.find_unit(session, "Zehe")
        unit.kind = "irgendwas_veraltetes"

    with session_scope(session_factory) as session:
        unit_service.ensure_default_units(session)

    with session_scope(session_factory) as session:
        unit = unit_service.find_unit(session, "Zehe")
        assert unit.kind == "mass"


def test_canonicalize_strips_price_prefix(session_factory) -> None:
    with session_scope(session_factory) as session:
        assert unit_service.canonicalize(session, "€/kg") == "kg"
        assert unit_service.canonicalize(session, "EUR/kg") == "kg"
        assert unit_service.canonicalize(session, "Preis/Stk") == "Stk"


def test_canonicalize_resolves_known_aliases(session_factory) -> None:
    with session_scope(session_factory) as session:
        assert unit_service.canonicalize(session, "Zehen") == "Zehe"
        assert unit_service.canonicalize(session, "kl") == "l"
        assert unit_service.canonicalize(session, "STK") == "Stk"


def test_canonicalize_is_case_insensitive_against_pool(session_factory) -> None:
    with session_scope(session_factory) as session:
        assert unit_service.canonicalize(session, "KG") == "kg"


def test_canonicalize_unknown_value_passthrough(session_factory) -> None:
    with session_scope(session_factory) as session:
        assert unit_service.canonicalize(session, "Krug") == "krug"


def test_validate_unit_accepts_pool_value_and_rejects_unknown(session_factory) -> None:
    with session_scope(session_factory) as session:
        assert unit_service.validate_unit(session, "kg") == "kg"
        with pytest.raises(ValueError):
            unit_service.validate_unit(session, "Krug")


def test_compatible_units_groups_mass_but_not_unrelated_units(session_factory) -> None:
    with session_scope(session_factory) as session:
        compatible_with_kg = set(unit_service.compatible_units(session, "kg"))
        # Zehe/EL/TL/Prise/Bund/Scheibe haben feste Grammnaeherungen (siehe price_service) und
        # gehoeren deshalb zur selben 'mass'-Gruppe wie g/kg.
        assert compatible_with_kg == {"g", "kg", "Zehe", "EL", "TL", "Prise", "Bund", "Scheibe", "Blatt"}
        assert "Stk" not in compatible_with_kg
        assert "Glas" not in compatible_with_kg

        compatible_with_stk = unit_service.compatible_units(session, "Stk")
        assert compatible_with_stk == ["Stk"]


def test_compatible_units_falls_back_to_input_when_unit_not_in_pool(session_factory) -> None:
    with session_scope(session_factory) as session:
        assert unit_service.compatible_units(session, "Krug") == ["Krug"]


def test_add_unit_rejects_duplicate_case_insensitive(session_factory) -> None:
    with session_scope(session_factory) as session:
        unit_service.add_unit(session, "Zweig")
        with pytest.raises(ValueError):
            unit_service.add_unit(session, "zweig")


def test_rename_unit_cascades_to_existing_rows(session_factory) -> None:
    with session_scope(session_factory) as session:
        ingredient = Ingredient(name="Knoblauch", normalized_name="knoblauch", default_unit="Zehe")
        session.add(ingredient)

    with session_scope(session_factory) as session:
        unit = unit_service.find_unit(session, "Zehe")
        unit_service.rename_unit(session, unit, "Knoblauchzehe")

    with session_scope(session_factory) as session:
        ingredient = session.execute(select(Ingredient)).scalar_one()
        assert ingredient.default_unit == "Knoblauchzehe"
        assert unit_service.find_unit(session, "Zehe") is None


def test_delete_unit_blocks_when_used_and_succeeds_when_unused(session_factory) -> None:
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Knoblauch", normalized_name="knoblauch", default_unit="Zehe"))
        unit_service.add_unit(session, "Ungenutzt")

    with session_scope(session_factory) as session:
        used_unit = unit_service.find_unit(session, "Zehe")
        with pytest.raises(ValueError):
            unit_service.delete_unit(session, used_unit)

        unused_unit = unit_service.find_unit(session, "Ungenutzt")
        unit_service.delete_unit(session, unused_unit)

    with session_scope(session_factory) as session:
        assert unit_service.find_unit(session, "Ungenutzt") is None
        assert unit_service.find_unit(session, "Zehe") is not None


def test_deactivate_unit_hides_it_from_active_list_only(session_factory) -> None:
    with session_scope(session_factory) as session:
        unit = unit_service.find_unit(session, "Glas")
        unit_service.deactivate_unit(unit)

    with session_scope(session_factory) as session:
        assert "Glas" not in unit_service.list_unit_names(session, active_only=True)
        assert "Glas" in unit_service.list_unit_names(session, active_only=False)
