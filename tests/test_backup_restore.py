import pytest

from app.config import AppConfig, build_sqlite_url
from app.db import create_engine_from_config, init_database
from app.services import backup_service


def test_app_config_builds_sqlite_url(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "backup.sqlite3")
    assert config.database_path == tmp_path / "backup.sqlite3"
    assert config.database_url == build_sqlite_url(tmp_path / "backup.sqlite3")


@pytest.fixture()
def initialized_config(tmp_path) -> AppConfig:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "app.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    return config


def test_create_backup_copies_database_with_timestamp(initialized_config) -> None:
    backup_path = backup_service.create_backup(initialized_config)
    assert backup_path.exists()
    assert backup_path.parent.name == "backups"
    assert backup_path.name.startswith("app_")


def test_create_backup_raises_when_database_missing(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "missing.sqlite3")
    with pytest.raises(FileNotFoundError):
        backup_service.create_backup(config)


def test_restore_backup_requires_explicit_confirmation(initialized_config) -> None:
    backup_path = backup_service.create_backup(initialized_config)
    with pytest.raises(backup_service.RestoreNotConfirmedError):
        backup_service.restore_backup(initialized_config, backup_path, confirm=False)


def test_restore_backup_replaces_database_content(initialized_config) -> None:
    backup_path = backup_service.create_backup(initialized_config)
    original_bytes = initialized_config.database_path.read_bytes()

    initialized_config.database_path.write_bytes(b"corrupted-not-really-sqlite")
    backup_service.restore_backup(initialized_config, backup_path, confirm=True)

    assert initialized_config.database_path.read_bytes() == original_bytes


def test_list_backups_returns_newest_first(initialized_config) -> None:
    first = backup_service.create_backup(initialized_config)
    backups = backup_service.list_backups(initialized_config)
    assert first in backups


def test_verify_integrity_reports_ok_for_fresh_database(initialized_config) -> None:
    engine = create_engine_from_config(initialized_config)
    ok, result = backup_service.verify_integrity(engine)
    assert ok is True
    assert result == "ok"
