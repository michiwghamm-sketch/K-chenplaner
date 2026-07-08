from app.config import AppConfig, build_sqlite_url


def test_app_config_builds_sqlite_url(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "backup.sqlite3")
    assert config.database_path == tmp_path / "backup.sqlite3"
    assert config.database_url == build_sqlite_url(tmp_path / "backup.sqlite3")
