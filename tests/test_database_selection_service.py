from __future__ import annotations

import pytest

from app.config import AppConfig
from app.db import create_engine_from_config, init_database
from app.services import database_selection_service as selection_service


@pytest.fixture()
def cloud_url(tmp_path) -> str:
    """SQLite-Datei als Cloud-Ersatz - sync_service ist dialektunabhaengig, also fuer Tests
    genauso gueltig wie eine echte Postgres-URL, aber ohne Netzwerkabhaengigkeit."""
    cloud_path = tmp_path / "fake_cloud.sqlite3"
    config = AppConfig.load(project_root=tmp_path, database_path=cloud_path)
    init_database(create_engine_from_config(config))
    return f"sqlite:///{cloud_path.as_posix()}"


@pytest.fixture()
def patch_offline_paths(tmp_path, monkeypatch):
    cache_path = tmp_path / "offline_cache.sqlite3"
    state_path = tmp_path / "offline_sync_state.json"
    monkeypatch.setattr(selection_service, "get_offline_cache_path", lambda: cache_path)
    monkeypatch.setattr(selection_service, "get_offline_sync_state_path", lambda: state_path)
    return cache_path, state_path


def test_reachable_cloud_without_cache_goes_live(tmp_path, cloud_url, patch_offline_paths):
    selection = selection_service.resolve_cloud_or_offline_mode(tmp_path, cloud_url)

    assert selection.is_offline_mode is False
    assert selection.config.database_url == cloud_url


def test_unreachable_cloud_without_cache_raises(tmp_path, patch_offline_paths, monkeypatch):
    monkeypatch.setattr(selection_service, "check_connectivity", lambda engine: "connection refused")

    with pytest.raises(selection_service.OfflineWithoutCacheError):
        selection_service.resolve_cloud_or_offline_mode(tmp_path, "postgresql://user:pw@unreachable/db")


def test_unreachable_cloud_with_existing_cache_uses_offline_mode(tmp_path, patch_offline_paths, monkeypatch):
    cache_path, _state_path = patch_offline_paths
    cache_config = AppConfig.load(project_root=tmp_path, database_path=cache_path)
    init_database(create_engine_from_config(cache_config))
    monkeypatch.setattr(selection_service, "check_connectivity", lambda engine: "connection refused")

    selection = selection_service.resolve_cloud_or_offline_mode(tmp_path, "postgresql://user:pw@unreachable/db")

    assert selection.is_offline_mode is True
    assert selection.config.database_path == cache_path


def test_reachable_cloud_with_fully_synced_cache_deletes_cache_and_goes_live(tmp_path, cloud_url, patch_offline_paths):
    cache_path, state_path = patch_offline_paths
    cache_config = AppConfig.load(project_root=tmp_path, database_path=cache_path)
    cache_engine = create_engine_from_config(cache_config)
    init_database(cache_engine)

    cloud_config = AppConfig.load(project_root=tmp_path, database_url=cloud_url)
    from app.db import create_engine_from_config as make_engine

    cloud_engine = make_engine(cloud_config)

    from app.services import sync_service

    sync_service.refresh_local_cache_from_cloud(cache_engine, cloud_engine, state_path)
    # Unter Windows blockiert eine offene SQLite-Verbindung das spaetere Loeschen der Datei -
    # in main.py ist das kein Problem, da dort kein zweiter Engine parallel offen gehalten wird.
    cache_engine.dispose()
    cloud_engine.dispose()

    selection = selection_service.resolve_cloud_or_offline_mode(tmp_path, cloud_url)

    assert selection.is_offline_mode is False
    assert not cache_path.exists()


def test_reachable_cloud_with_pending_offline_changes_stays_offline(tmp_path, cloud_url, patch_offline_paths):
    cache_path, state_path = patch_offline_paths
    cache_config = AppConfig.load(project_root=tmp_path, database_path=cache_path)
    cache_engine = create_engine_from_config(cache_config)
    init_database(cache_engine)

    cloud_config = AppConfig.load(project_root=tmp_path, database_url=cloud_url)
    from app.db import create_engine_from_config as make_engine
    from app.db import create_session_factory, session_scope
    from app.models import Ingredient
    from app.services import sync_service

    cloud_engine = make_engine(cloud_config)
    sync_service.refresh_local_cache_from_cloud(cache_engine, cloud_engine, state_path)

    with session_scope(create_session_factory(cache_engine)) as session:
        session.add(Ingredient(name="Offline-Zutat", normalized_name="offline-zutat"))

    selection = selection_service.resolve_cloud_or_offline_mode(tmp_path, cloud_url)

    assert selection.is_offline_mode is True
    assert cache_path.exists()
