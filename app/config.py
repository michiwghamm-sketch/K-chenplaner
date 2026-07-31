from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB_FILENAME = "zeltlager_kueche.sqlite3"


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    data_dir: Path
    instance_dir: Path
    database_path: Path | None
    database_url: str

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite:")

    @classmethod
    def load(
        cls,
        project_root: Path | None = None,
        database_path: Path | None = None,
        database_url: str | None = None,
    ) -> "AppConfig":
        """Laedt die Konfiguration. `database_url` (z. B. eine Postgres-Connection-String
        fuer den Cloud-Betrieb) hat Vorrang vor `database_path` (lokale SQLite-Datei)."""
        root = project_root or Path(__file__).resolve().parent.parent
        instance_dir = root / "instance"
        instance_dir.mkdir(parents=True, exist_ok=True)

        if database_url:
            return cls(
                project_root=root,
                data_dir=root / "data",
                instance_dir=instance_dir,
                database_path=None,
                database_url=normalize_postgres_url(database_url),
            )

        resolved_database_path = resolve_database_path(root, database_path)
        resolved_database_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=root,
            data_dir=root / "data",
            instance_dir=instance_dir,
            database_path=resolved_database_path,
            database_url=build_sqlite_url(resolved_database_path),
        )


def resolve_database_path(project_root: Path, database_path: Path | None = None) -> Path:
    env_value = os.getenv("ZELAKUECHE_DB_PATH")
    candidate = database_path or (Path(env_value) if env_value else project_root / "instance" / DEFAULT_DB_FILENAME)
    return candidate if candidate.is_absolute() else (project_root / candidate).resolve()


def build_sqlite_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.as_posix()}"


def normalize_postgres_url(database_url: str) -> str:
    """Neon/Standard-Postgres-URLs kommen als 'postgresql://...' - SQLAlchemy braucht das
    Treiber-Suffix, damit psycopg (statt des nicht mitgelieferten psycopg2) verwendet wird."""
    database_url = database_url.strip()
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg://" + database_url[len("postgres://") :]
    return database_url
