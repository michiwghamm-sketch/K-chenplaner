from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_DB_FILENAME = "zeltlager_kueche.sqlite3"


@dataclass(slots=True)
class AppConfig:
    project_root: Path
    data_dir: Path
    docs_dir: Path
    instance_dir: Path
    database_path: Path
    database_url: str

    @classmethod
    def load(cls, project_root: Path | None = None, database_path: Path | None = None) -> "AppConfig":
        root = project_root or Path(__file__).resolve().parent.parent
        instance_dir = root / "instance"
        instance_dir.mkdir(parents=True, exist_ok=True)

        resolved_database_path = resolve_database_path(root, database_path)
        resolved_database_path.parent.mkdir(parents=True, exist_ok=True)

        return cls(
            project_root=root,
            data_dir=root / "data",
            docs_dir=root / "docs",
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
