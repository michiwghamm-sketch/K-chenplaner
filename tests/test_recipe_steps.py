from app.db import session_scope
from app.models import Recipe, RecipeStep
from app.services import recipe_service


def _build_recipe(session) -> Recipe:
    recipe = Recipe(name="Testrezept", normalized_name="testrezept", default_portions=10)
    session.add(recipe)
    session.flush()
    return recipe


def test_create_step_increments_sort_order(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        recipe_service.create_step(session, recipe, title="Bruehen einweichen", description="In Milch einweichen", duration_minutes=10)
        recipe_service.create_step(session, recipe, title="Kartoffeln kochen", description="Weich garen", duration_minutes=20)
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        steps = sorted(recipe.steps, key=lambda s: s.sort_order)
        assert [s.title for s in steps] == ["Bruehen einweichen", "Kartoffeln kochen"]
        assert [s.sort_order for s in steps] == [1, 2]
        assert recipe_service.total_step_duration_minutes(recipe) == 30


def test_update_step_changes_fields(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        step = recipe_service.create_step(session, recipe, title="Alt", duration_minutes=5)
        recipe_id = recipe.id
        step_id = step.id

    with session_scope(session_factory) as session:
        step = session.get(RecipeStep, step_id)
        recipe_service.update_step(step, title="Neu", duration_minutes=15)

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        assert recipe.steps[0].title == "Neu"
        assert recipe.steps[0].duration_minutes == 15


def test_delete_step_removes_it(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        step = recipe_service.create_step(session, recipe, title="Weg")
        recipe_id = recipe.id
        step_id = step.id

    with session_scope(session_factory) as session:
        step = session.get(RecipeStep, step_id)
        recipe_service.delete_step(session, step)

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        assert recipe.steps == []


def test_move_step_swaps_with_neighbor(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        recipe_service.create_step(session, recipe, title="Erst")
        recipe_service.create_step(session, recipe, title="Zweitens")
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        first_step = next(s for s in recipe.steps if s.title == "Erst")
        recipe_service.move_step(session, recipe, first_step, direction=1)

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        ordered = sorted(recipe.steps, key=lambda s: s.sort_order)
        assert [s.title for s in ordered] == ["Zweitens", "Erst"]


def test_move_step_beyond_bounds_is_noop(session_factory) -> None:
    with session_scope(session_factory) as session:
        recipe = _build_recipe(session)
        only_step = recipe_service.create_step(session, recipe, title="Einzig")
        recipe_id = recipe.id
        step_id = only_step.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        step = session.get(RecipeStep, step_id)
        recipe_service.move_step(session, recipe, step, direction=-1)
        recipe_service.move_step(session, recipe, step, direction=1)
        assert step.sort_order == 1
