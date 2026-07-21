from decimal import Decimal

from app.db import session_scope
from app.models import Ingredient, IngredientPrice, Recipe
from app.services import export_service, recipe_service


def test_export_recipe_to_pdf_renders_structured_steps(session_factory, tmp_path) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Schrittrezept", normalized_name="schrittrezept", default_portions=10)
        session.add(recipe)
        ingredient = Ingredient(name="Wasser", normalized_name="wasser", default_unit="l")
        session.add(ingredient)
        session.flush()
        recipe_service.add_ingredient_to_recipe(session, recipe, ingredient_id=ingredient.id, quantity=Decimal("1.000"), unit="l")
        recipe_service.create_step(session, recipe, title="Wasser kochen", description="Topf aufsetzen", duration_minutes=10)
        recipe_service.create_step(session, recipe, title="Abgiessen", duration_minutes=2)
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        cost_result = recipe_service.calculate_recipe_cost(session, recipe, portions=10)
        out_path = tmp_path / "schrittrezept.pdf"
        export_service.export_recipe_to_pdf(recipe, cost_result, out_path)
        assert out_path.read_bytes().startswith(b"%PDF")


def test_export_recipe_to_pdf_creates_file_with_components(session_factory, tmp_path) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Koettbullar", normalized_name="koettbullar", default_portions=100, instructions="Alles vermengen.\nBraten.")
        session.add(recipe)
        session.flush()

        meatballs = recipe_service.create_component(session, recipe, "Koettbullar")
        sauce = recipe_service.create_component(session, recipe, "Soße")

        beef = Ingredient(name="Gemischtes Hackfleisch", normalized_name="gemischtes hackfleisch", default_unit="kg")
        beef.prices.append(IngredientPrice(price_per_unit=Decimal("16.00"), unit="kg", year=2026))
        cream = Ingredient(name="Laktosefreie Sahne", normalized_name="laktosefreie sahne", default_unit="l")
        session.add_all([beef, cream])
        session.flush()

        recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=beef.id, quantity=Decimal("10.000"), unit="kg", component_id=meatballs.id
        )
        recipe_service.add_ingredient_to_recipe(
            session, recipe, ingredient_id=cream.id, quantity=Decimal("5.000"), unit="l", component_id=sauce.id
        )
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        cost_result = recipe_service.calculate_recipe_cost(session, recipe, portions=100, year=2026)

        out_path = tmp_path / "koettbullar.pdf"
        result_path = export_service.export_recipe_to_pdf(recipe, cost_result, out_path)

        assert result_path == out_path
        assert out_path.exists()
        assert out_path.read_bytes().startswith(b"%PDF")
        assert out_path.stat().st_size > 1000


def test_export_recipe_to_pdf_handles_missing_price_and_no_component(session_factory, tmp_path) -> None:
    with session_scope(session_factory) as session:
        recipe = Recipe(name="Testgericht", normalized_name="testgericht", default_portions=10)
        session.add(recipe)
        ingredient = Ingredient(name="Geheimzutat", normalized_name="geheimzutat", default_unit="kg")
        session.add(ingredient)
        session.flush()
        recipe_service.add_ingredient_to_recipe(session, recipe, ingredient_id=ingredient.id, quantity=Decimal("1.000"), unit="kg")
        recipe_id = recipe.id

    with session_scope(session_factory) as session:
        recipe = session.get(Recipe, recipe_id)
        cost_result = recipe_service.calculate_recipe_cost(session, recipe, portions=10)

        out_path = tmp_path / "testgericht.pdf"
        export_service.export_recipe_to_pdf(recipe, cost_result, out_path)

        assert out_path.exists()
        assert out_path.read_bytes().startswith(b"%PDF")
