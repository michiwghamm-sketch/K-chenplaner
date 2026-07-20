from sqlalchemy import select

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import Ingredient
from scripts.dedupe_ingredients import run_dedupe, write_report


def _seed_duplicates(config: AppConfig) -> None:
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Zwiebel", normalized_name="zwiebel"))
        session.add(Ingredient(name="Zwiebeln", normalized_name="zwiebeln"))
        session.add(Ingredient(name="Tomate", normalized_name="tomate"))


def test_dry_run_does_not_modify_database(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    _seed_duplicates(config)

    log = run_dedupe(config, apply=False)
    assert len(log) == 1
    assert {log[0].keep_name, log[0].remove_name} == {"Zwiebel", "Zwiebeln"}

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        names = {i.name for i in session.execute(select(Ingredient)).scalars()}
        assert names == {"Zwiebel", "Zwiebeln", "Tomate"}


def test_apply_merges_and_removes_duplicate(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    _seed_duplicates(config)

    log = run_dedupe(config, apply=True)
    assert len(log) == 1

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        names = {i.name for i in session.execute(select(Ingredient)).scalars()}
        assert names == {"Zwiebel", "Tomate"}
        kept = session.execute(select(Ingredient).where(Ingredient.name == "Zwiebel")).scalar_one()
        assert {a.alias for a in kept.aliases} == {"Zwiebeln"}


def test_apply_handles_triangle_of_similar_ingredients_without_error(tmp_path) -> None:
    """Regression: three mutually-similar ingredients can produce two candidate pairs that both
    name the same ingredient as 'remove' (Champignon~Champignons and Champignons~Champigons,
    while Champignon~Champigons falls just under the auto-merge threshold). The second pair must
    redirect to the already-merged survivor instead of deleting an already-deleted ingredient."""
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Champignon", normalized_name="champignon"))
        session.add(Ingredient(name="Champignons", normalized_name="champignons"))
        session.add(Ingredient(name="Champigons", normalized_name="champigons"))

    log = run_dedupe(config, apply=True)
    assert len(log) == 2

    with session_scope(session_factory) as session:
        remaining = session.execute(select(Ingredient)).scalars().all()
        assert len(remaining) == 1
        survivor = remaining[0]
        assert {a.alias for a in survivor.aliases} == {"Champignon", "Champignons", "Champigons"} - {survivor.name}


def test_write_report_lists_merges(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    _seed_duplicates(config)
    log = run_dedupe(config, apply=True)

    report_path = write_report(tmp_path, log, applied=True)
    content = report_path.read_text(encoding="utf-8")
    assert "Zwiebel" in content
    assert "Zwiebeln" in content
    assert "angewendet" in content
