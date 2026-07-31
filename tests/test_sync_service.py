from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import Ingredient, Recipe, RecipeIngredient, Unit
from app.services import sync_service


@pytest.fixture()
def local_engine(tmp_path):
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "local.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    return engine


@pytest.fixture()
def cloud_engine(tmp_path):
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "cloud.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    return engine


def _add_ingredient(engine, *, name: str) -> int:
    with session_scope(create_session_factory(engine)) as session:
        ingredient = Ingredient(name=name, normalized_name=name.lower())
        session.add(ingredient)
        session.flush()
        return ingredient.id


def test_analyze_flags_offline_new_row_as_pushable(local_engine, cloud_engine):
    _add_ingredient(local_engine, name="Nudeln")

    plan = sync_service.analyze(local_engine, cloud_engine, last_synced_at=None)

    assert "ingredients" in plan.new_rows
    assert [row["name"] for row in plan.new_rows["ingredients"]] == ["Nudeln"]
    assert plan.conflicts == []


def test_apply_pushes_new_row_with_remapped_id_and_fixes_fk_children(local_engine, cloud_engine):
    # Realistischer Ablauf: der Offline-Cache stammt immer aus einem echten Cloud-Pull (siehe
    # database_selection_service/cache_priming), lokale und Cloud-IDs stimmen bis zu diesem
    # Zeitpunkt also ueberein. "Andere Zutat" existiert schon vorher in der Cloud und damit auch
    # im frisch gezogenen lokalen Cache.
    other_id = _add_ingredient(cloud_engine, name="Andere Zutat")
    sync_state_path = tmp_sync_state_path(local_engine)
    sync_service.refresh_local_cache_from_cloud(local_engine, cloud_engine, sync_state_path)
    last_synced_at = sync_service.read_last_synced_at(sync_state_path)
    time.sleep(1.1)  # created_at/updated_at haben Sekundenaufloesung

    # Offline wird eine neue Zutat + ein neues Rezept mit Verknuepfung angelegt.
    ingredient_id = _add_ingredient(local_engine, name="Reis")
    assert ingredient_id != other_id  # neue ID jenseits des uebernommenen Cloud-Standes
    with session_scope(create_session_factory(local_engine)) as session:
        recipe = Recipe(name="Reispfanne", normalized_name="reispfanne")
        recipe.ingredients.append(RecipeIngredient(ingredient_id=ingredient_id, quantity=1, unit="kg", sort_order=1))
        session.add(recipe)

    # Waehrenddessen legt jemand anderes unabhaengig eine eigene neue Zutat in der Cloud an -
    # das darf die Zuordnung der offline neu angelegten Zutat nicht durcheinanderbringen.
    _add_ingredient(cloud_engine, name="Cloud-Neuzugang")

    plan = sync_service.analyze(local_engine, cloud_engine, last_synced_at)
    report = sync_service.apply(local_engine, cloud_engine, plan, {}, sync_state_path)

    assert report.pushed_rows >= 2
    with session_scope(create_session_factory(cloud_engine)) as session:
        pushed_recipe = session.query(Recipe).filter_by(normalized_name="reispfanne").one()
        assert len(pushed_recipe.ingredients) == 1
        linked_ingredient = pushed_recipe.ingredients[0].ingredient
        assert linked_ingredient.name == "Reis"

        # Die anderen Zutaten muessen unangetastet geblieben sein.
        assert session.query(Ingredient).filter_by(normalized_name="andere zutat").one().name == "Andere Zutat"
        assert session.query(Ingredient).filter_by(normalized_name="cloud-neuzugang").one().name == "Cloud-Neuzugang"


def test_cloud_only_change_is_not_pushed_and_not_flagged_as_conflict(local_engine, cloud_engine):
    ingredient_id = _add_ingredient(local_engine, name="Zwiebel")
    sync_state_path = tmp_sync_state_path(local_engine)
    plan = sync_service.analyze(local_engine, cloud_engine, last_synced_at=None)
    sync_service.apply(local_engine, cloud_engine, plan, {}, sync_state_path)
    last_synced_at = sync_service.read_last_synced_at(sync_state_path)

    time.sleep(1.1)  # updated_at hat Sekundenaufloesung
    with session_scope(create_session_factory(cloud_engine)) as session:
        cloud_ingredient = session.query(Ingredient).filter_by(normalized_name="zwiebel").one()
        cloud_ingredient.notes = "in der Cloud ergaenzt"

    plan2 = sync_service.analyze(local_engine, cloud_engine, last_synced_at)

    assert plan2.new_rows == {}
    assert plan2.updated_rows == {}
    assert plan2.conflicts == []


def test_both_sides_changed_since_last_sync_is_a_conflict_and_resolution_is_honored(local_engine, cloud_engine):
    ingredient_id = _add_ingredient(local_engine, name="Karotte")
    sync_state_path = tmp_sync_state_path(local_engine)
    plan = sync_service.analyze(local_engine, cloud_engine, last_synced_at=None)
    sync_service.apply(local_engine, cloud_engine, plan, {}, sync_state_path)
    last_synced_at = sync_service.read_last_synced_at(sync_state_path)

    time.sleep(1.1)
    with session_scope(create_session_factory(local_engine)) as session:
        session.query(Ingredient).filter_by(normalized_name="karotte").one().notes = "offline geaendert"
    with session_scope(create_session_factory(cloud_engine)) as session:
        session.query(Ingredient).filter_by(normalized_name="karotte").one().notes = "in der cloud geaendert"

    plan2 = sync_service.analyze(local_engine, cloud_engine, last_synced_at)
    assert len(plan2.conflicts) == 1
    conflict = plan2.conflicts[0]

    report = sync_service.apply(
        local_engine, cloud_engine, plan2, {conflict.key: "local"}, sync_state_path
    )
    assert report.conflicts_resolved_local == 1
    with session_scope(create_session_factory(cloud_engine)) as session:
        assert session.query(Ingredient).filter_by(normalized_name="karotte").one().notes == "offline geaendert"


def test_table_without_updated_at_always_conflicts_when_differing(local_engine, cloud_engine):
    # Units werden beim init_database identisch geseedet - wir aendern eine Einheit nur lokal,
    # ohne dass es dafuer einen Zeitstempel gibt, an dem sich "seit wann" festmachen liesse.
    with session_scope(create_session_factory(local_engine)) as session:
        unit = session.query(Unit).filter_by(name="kg").one()
        unit.sort_order = 99

    plan = sync_service.analyze(local_engine, cloud_engine, last_synced_at=None)

    assert any(c.table_name == "units" for c in plan.conflicts)


def tmp_sync_state_path(engine):
    # Nutzt denselben tmp_path-Ordner wie die Test-Engine (SQLite-Datei liegt dort), damit pro
    # Test ein isolierter Sync-State verwendet wird.
    db_path = engine.url.database
    from pathlib import Path

    return Path(db_path).parent / "sync_state.json"
