from decimal import Decimal

from sqlalchemy import select

from app.config import AppConfig
from app.db import create_engine_from_config, create_session_factory, init_database, session_scope
from app.models import Ingredient, Recipe, RecipeIngredient
from app.services import ingredient_service
from scripts.dedupe_ingredients import run_dedupe, write_report


def _seed_duplicates(config: AppConfig) -> None:
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Zwiebel", normalized_name="zwiebel"))
        session.add(Ingredient(name="Zwiebeln", normalized_name="zwiebeln"))
        session.add(Ingredient(name="Tomate", normalized_name="tomate"))


def test_dry_run_does_not_modify_database_or_create_backup(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    _seed_duplicates(config)

    result = run_dedupe(config, apply=False)
    assert len(result.merged) == 1
    assert {result.merged[0].keep_name, result.merged[0].remove_name} == {"Zwiebel", "Zwiebeln"}
    assert result.backup_path is None
    assert not (tmp_path / "backups").exists()

    engine = create_engine_from_config(config)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        names = {i.name for i in session.execute(select(Ingredient)).scalars()}
        assert names == {"Zwiebel", "Zwiebeln", "Tomate"}


def test_apply_merges_removes_duplicate_and_creates_backup(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    _seed_duplicates(config)

    result = run_dedupe(config, apply=True)
    assert len(result.merged) == 1
    assert result.backup_path is not None
    assert result.backup_path.exists()

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

    result = run_dedupe(config, apply=True)
    assert len(result.merged) == 2

    with session_scope(session_factory) as session:
        remaining = session.execute(select(Ingredient)).scalars().all()
        assert len(remaining) == 1
        survivor = remaining[0]
        assert {a.alias for a in survivor.aliases} == {"Champignon", "Champignons", "Champigons"} - {survivor.name}


def test_dry_run_deduplicates_candidates_the_same_way_as_apply(tmp_path) -> None:
    """The redirect bookkeeping must dedupe overlapping candidates even without ever calling
    merge_ingredients(), so a dry-run report matches what --apply would actually do."""
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Champignon", normalized_name="champignon"))
        session.add(Ingredient(name="Champignons", normalized_name="champignons"))
        session.add(Ingredient(name="Champigons", normalized_name="champigons"))

    result = run_dedupe(config, apply=False)
    assert len(result.merged) == 2


def test_alias_orphan_duplicate_is_merged_and_reported_with_affected_recipes(tmp_path) -> None:
    """Reproduces the real-world state found in the live database: a prior merge run set an alias,
    but the duplicate ingredient row itself was never deleted (e.g. a later reimport brought back
    the pre-merge state). run_dedupe() must finish that interrupted merge and report which recipe
    was affected."""
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Zwiebelsuppe", normalized_name="zwiebelsuppe")
        keep = Ingredient(name="Zwiebel", normalized_name="zwiebel")
        session.add_all([recipe, keep])
        session.flush()
        ingredient_service.add_alias(session, keep, "Zwiebeln")
        duplicate = Ingredient(name="Zwiebeln", normalized_name="zwiebeln")
        session.add(duplicate)
        session.flush()
        recipe.ingredients.append(
            RecipeIngredient(ingredient=duplicate, quantity=Decimal("0.300"), unit="kg", sort_order=1)
        )

    result = run_dedupe(config, apply=True)
    assert len(result.merged) == 1
    assert result.merged[0].keep_name == "Zwiebel"
    assert result.merged[0].remove_name == "Zwiebeln"
    assert result.merged[0].affected_recipes == ["Zwiebelsuppe (0.300 kg)"]

    with session_scope(session_factory) as session:
        names = {i.name for i in session.execute(select(Ingredient)).scalars()}
        assert names == {"Zwiebel"}
        recipe = session.execute(select(Recipe)).scalar_one()
        assert recipe.ingredients[0].ingredient.name == "Zwiebel"


def test_review_tier_lists_lower_confidence_pairs_without_merging_them(tmp_path) -> None:
    """'Balsamico'/'Balsamiko' is a real typo pair but only ~89% similar - below the 93% auto-merge
    threshold. It must show up as a manual-review candidate, and must never be merged automatically."""
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Balsamico", normalized_name="balsamico"))
        session.add(Ingredient(name="Balsamiko", normalized_name="balsamiko"))

    result = run_dedupe(config, apply=True)
    assert result.merged == []
    assert len(result.review) == 1
    assert {result.review[0].name_a, result.review[0].name_b} == {"Balsamico", "Balsamiko"}


def test_review_tier_still_surfaces_an_unrelated_pair_sharing_a_merged_ingredient(tmp_path) -> None:
    """Regression: found on the real database. 'Champignons'/'Champigons' auto-merge (95%), but
    'Champigons'/'Champingions' is a *different*, still-unresolved duplicate pair (91%, below the
    93% auto-merge threshold) that happens to share 'Champigons' with the first pair. It must still
    be reported for manual review - it must not silently disappear just because one of its two
    ingredients was touched by an unrelated merge."""
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    engine = create_engine_from_config(config)
    init_database(engine)
    session_factory = create_session_factory(engine)
    with session_scope(session_factory) as session:
        session.add(Ingredient(name="Champignons", normalized_name="champignons"))
        session.add(Ingredient(name="Champigons", normalized_name="champigons"))
        session.add(Ingredient(name="Champingions", normalized_name="champingions"))

    result = run_dedupe(config, apply=True)
    assert len(result.merged) == 1
    assert {result.merged[0].keep_name, result.merged[0].remove_name} == {"Champigons", "Champignons"}
    assert len(result.review) == 1
    assert {result.review[0].name_a, result.review[0].name_b} == {"Champigons", "Champingions"}

    with session_scope(session_factory) as session:
        names = {i.name for i in session.execute(select(Ingredient)).scalars()}
        assert "Champingions" in names
        assert len(names) == 2


def test_write_report_lists_merges_review_section_and_backup(tmp_path) -> None:
    config = AppConfig.load(project_root=tmp_path, database_path=tmp_path / "instance" / "dedupe.sqlite3")
    _seed_duplicates(config)
    result = run_dedupe(config, apply=True)

    report_path = write_report(tmp_path, result, applied=True)
    content = report_path.read_text(encoding="utf-8")
    assert "Zwiebel" in content
    assert "Zwiebeln" in content
    assert "angewendet" in content
    assert "Manuell zu pruefen" in content
    assert str(result.backup_path) in content
