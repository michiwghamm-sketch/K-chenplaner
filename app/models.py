from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def created_timestamp_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def updated_timestamp_column() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class Unit(Base):
    """Pool der gueltigen Mengeneinheiten (z. B. 'kg', 'Stk', 'Bund') fuer Zutaten und Rezepte.

    'kind' gruppiert ineinander umrechenbare Einheiten (z. B. 'mass' fuer g/kg), damit eine
    Rezeptzutat nur zwischen kompatiblen Einheiten wechseln kann. Einheiten ohne Umrechnungspartner
    bekommen ihren eigenen Namen als kind (z. B. 'Bund' -> kind 'bund'), sind also nur zu sich
    selbst kompatibel.
    """

    __tablename__ = "units"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Ingredient(Base):
    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    default_unit: Mapped[Optional[str]] = mapped_column(String(50))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    storage_type: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    barcode: Mapped[Optional[str]] = mapped_column(String(64))
    # Gecachte Anzeige des verknuepften Produkts (z. B. "Ketchup (Jardin bio, 560 g)"), damit die UI
    # das nicht bei jedem Laden erneut ueber die API nachschlagen muss.
    barcode_product_label: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    aliases: Mapped[list["IngredientAlias"]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")
    prices: Mapped[list["IngredientPrice"]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")
    price_profile: Mapped[Optional["IngredientPriceProfile"]] = relationship(
        back_populates="ingredient", cascade="all, delete-orphan", uselist=False
    )
    recipe_links: Mapped[list["RecipeIngredient"]] = relationship(back_populates="ingredient")
    shopping_items: Mapped[list["ShoppingListItem"]] = relationship(back_populates="ingredient")


class IngredientAlias(Base):
    __tablename__ = "ingredient_aliases"
    __table_args__ = (UniqueConstraint("ingredient_id", "alias", name="uq_ingredient_alias"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    alias: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    ingredient: Mapped["Ingredient"] = relationship(back_populates="aliases")


class IngredientPrice(Base):
    __tablename__ = "ingredient_prices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    # 4 statt 2 Nachkommastellen: Gramm-/ml-Preise (z. B. aus Open-Prices-Umrechnung, "0.0076 EUR/g")
    # brauchen mehr Praezision als klassische "2,50 EUR"-Preise - siehe convert_price_per_unit(),
    # das explizit auf 4 Nachkommastellen rundet.
    price_per_unit: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(255))
    store: Mapped[Optional[str]] = mapped_column(String(255))
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    year: Mapped[Optional[int]] = mapped_column(Integer, index=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    ingredient: Mapped["Ingredient"] = relationship(back_populates="prices")


class OpenPricesCategory(Base):
    __tablename__ = "open_prices_categories"

    tag: Mapped[str] = mapped_column(String(255), primary_key=True)
    name_de: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    name_en: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    parents_json: Mapped[Optional[str]] = mapped_column(Text)
    synonyms_json: Mapped[Optional[str]] = mapped_column(Text)
    raw_json: Mapped[Optional[str]] = mapped_column(Text)
    updated_at: Mapped[datetime] = updated_timestamp_column()

    ingredient_profiles: Mapped[list["IngredientPriceProfile"]] = relationship(back_populates="category")


class IngredientPriceProfile(Base):
    __tablename__ = "ingredient_price_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, unique=True, index=True)
    category_tag: Mapped[Optional[str]] = mapped_column(ForeignKey("open_prices_categories.tag"), index=True)
    search_terms: Mapped[Optional[str]] = mapped_column(Text)
    lookup_mode: Mapped[str] = mapped_column(String(50), default="category", nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="needs_review", nullable=False, index=True)
    confidence: Mapped[Optional[str]] = mapped_column(String(50))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    ingredient: Mapped["Ingredient"] = relationship(back_populates="price_profile")
    category: Mapped[Optional["OpenPricesCategory"]] = relationship(back_populates="ingredient_profiles")


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    diet_type: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    meal_type: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    default_portions: Mapped[Optional[int]] = mapped_column(Integer)
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="recipe", cascade="all, delete-orphan")
    components: Mapped[list["RecipeComponent"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeComponent.sort_order"
    )
    steps: Mapped[list["RecipeStep"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeStep.sort_order"
    )
    versions: Mapped[list["RecipeVersion"]] = relationship(
        back_populates="recipe", cascade="all, delete-orphan", order_by="RecipeVersion.version_number"
    )
    meal_plan_entries: Mapped[list["MealPlanEntry"]] = relationship(back_populates="recipe")
    feedback_entries: Mapped[list["RecipeFeedback"]] = relationship(back_populates="recipe")


class RecipeStep(Base):
    """Ein Arbeitsschritt der Kochanleitung (Titel, Beschreibung, ungefaehre Dauer in Minuten)."""

    __tablename__ = "recipe_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)
    duration_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    recipe: Mapped["Recipe"] = relationship(back_populates="steps")


class RecipeComponent(Base):
    """Ein Teilstueck eines Rezepts, z. B. 'Semmelknoedel', 'Soße', 'Kartoffelbrei'."""

    __tablename__ = "recipe_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    recipe: Mapped["Recipe"] = relationship(back_populates="components")
    ingredients: Mapped[list["RecipeIngredient"]] = relationship(
        back_populates="component", order_by="RecipeIngredient.sort_order"
    )


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False, index=True)
    # Nullable: Zutaten ohne Teilstueck-Zuordnung (z. B. Altdaten aus dem Excel-Import) landen in "Sonstiges".
    component_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recipe_components.id"), index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    price_unit: Mapped[Optional[str]] = mapped_column(String(50))
    optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    recipe: Mapped["Recipe"] = relationship(back_populates="ingredients")
    component: Mapped[Optional["RecipeComponent"]] = relationship(back_populates="ingredients")
    ingredient: Mapped["Ingredient"] = relationship(back_populates="recipe_links")


class RecipeVersion(Base):
    """Historischer Schnappschuss der Zutatenmengen eines Rezepts (Changelog)."""

    __tablename__ = "recipe_versions"
    __table_args__ = (UniqueConstraint("recipe_id", "version_number", name="uq_recipe_version_number"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False, index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    change_note: Mapped[Optional[str]] = mapped_column(Text)
    scale_factor: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    default_portions: Mapped[Optional[int]] = mapped_column(Integer)
    # JSON-Schnappschuss (Teilstueck/Zutat/Menge/Einheit) - textuell eingefroren, damit spaetere
    # Umbenennungen/Loeschungen von Zutaten oder Teilstuecken die Historie nicht veraendern.
    ingredients_snapshot: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_timestamp_column()

    recipe: Mapped["Recipe"] = relationship(back_populates="versions")


class CampYear(Base):
    __tablename__ = "camp_years"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    start_date: Mapped[Optional[date]] = mapped_column(Date)
    end_date: Mapped[Optional[date]] = mapped_column(Date)
    participant_count_children: Mapped[Optional[int]] = mapped_column(Integer)
    participant_count_adults: Mapped[Optional[int]] = mapped_column(Integer)
    participant_count_total: Mapped[Optional[int]] = mapped_column(Integer)
    location: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    meal_plan_entries: Mapped[list["MealPlanEntry"]] = relationship(back_populates="camp_year", cascade="all, delete-orphan")
    feedback_entries: Mapped[list["RecipeFeedback"]] = relationship(back_populates="camp_year", cascade="all, delete-orphan")
    shopping_lists: Mapped[list["ShoppingList"]] = relationship(back_populates="camp_year", cascade="all, delete-orphan")
    camp_days: Mapped[list["CampDay"]] = relationship(back_populates="camp_year", cascade="all, delete-orphan")


class CampDay(Base):
    """Ein Tag innerhalb eines Camp-Jahrs (Zeltlager-Woche), z. B. fuer den Tagesverantwortlichen."""

    __tablename__ = "camp_days"
    __table_args__ = (UniqueConstraint("camp_year_id", "day_date", name="uq_camp_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camp_year_id: Mapped[int] = mapped_column(ForeignKey("camp_years.id"), nullable=False, index=True)
    day_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    weekday: Mapped[Optional[str]] = mapped_column(String(30))
    responsible_person: Mapped[Optional[str]] = mapped_column(String(255))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    camp_year: Mapped["CampYear"] = relationship(back_populates="camp_days")


class MealPlanEntry(Base):
    __tablename__ = "meal_plan_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camp_year_id: Mapped[int] = mapped_column(ForeignKey("camp_years.id"), nullable=False, index=True)
    meal_date: Mapped[Optional[date]] = mapped_column(Date, index=True)
    weekday: Mapped[Optional[str]] = mapped_column(String(30))
    meal_type: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    recipe_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recipes.id"), index=True)
    planned_portions: Mapped[Optional[int]] = mapped_column(Integer)
    target_group: Mapped[Optional[str]] = mapped_column(String(100))
    status: Mapped[Optional[str]] = mapped_column(String(50))
    shopping_date: Mapped[Optional[date]] = mapped_column(Date)
    shopping_group: Mapped[Optional[str]] = mapped_column(String(100))
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    camp_year: Mapped["CampYear"] = relationship(back_populates="meal_plan_entries")
    recipe: Mapped[Optional["Recipe"]] = relationship(back_populates="meal_plan_entries")
    feedback: Mapped[Optional["RecipeFeedback"]] = relationship(back_populates="meal_plan_entry", uselist=False)


class RecipeFeedback(Base):
    __tablename__ = "recipe_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camp_year_id: Mapped[int] = mapped_column(ForeignKey("camp_years.id"), nullable=False, index=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False, index=True)
    # Verknuepft das Feedback mit einer konkreten Mahlzeit im Wochenplan (ein Feedback je Mahlzeit-Slot).
    # Nullable, weil aus Excel importiertes Alt-Feedback keiner konkreten Mahlzeit zugeordnet werden kann.
    meal_plan_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("meal_plan_entries.id"), unique=True, index=True
    )
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    repeat_next_time: Mapped[Optional[bool]] = mapped_column(Boolean)
    quantity_sufficient: Mapped[Optional[str]] = mapped_column(String(50))
    planned_portions: Mapped[Optional[int]] = mapped_column(Integer)
    cooked_portions: Mapped[Optional[int]] = mapped_column(Integer)
    leftover_quantity: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    leftover_unit: Mapped[Optional[str]] = mapped_column(String(50))
    quantity_factor_next_time: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3))
    process_tips: Mapped[Optional[str]] = mapped_column(Text)
    what_went_well: Mapped[Optional[str]] = mapped_column(Text)
    what_to_change: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    camp_year: Mapped["CampYear"] = relationship(back_populates="feedback_entries")
    recipe: Mapped["Recipe"] = relationship(back_populates="feedback_entries")
    meal_plan_entry: Mapped[Optional["MealPlanEntry"]] = relationship(back_populates="feedback")


class ShoppingList(Base):
    __tablename__ = "shopping_lists"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camp_year_id: Mapped[int] = mapped_column(ForeignKey("camp_years.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    camp_year: Mapped["CampYear"] = relationship(back_populates="shopping_lists")
    items: Mapped[list["ShoppingListItem"]] = relationship(back_populates="shopping_list", cascade="all, delete-orphan")


class ShoppingListItem(Base):
    __tablename__ = "shopping_list_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shopping_list_id: Mapped[int] = mapped_column(ForeignKey("shopping_lists.id"), nullable=False, index=True)
    ingredient_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ingredients.id"), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    unit: Mapped[Optional[str]] = mapped_column(String(50))
    # Gleiche Praezisions-Begruendung wie IngredientPrice.price_per_unit.
    estimated_price_per_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 4))
    estimated_total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    storage_type: Mapped[Optional[str]] = mapped_column(String(100))
    needed_date: Mapped[Optional[date]] = mapped_column(Date)
    shopping_date: Mapped[Optional[date]] = mapped_column(Date)
    store: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[Optional[str]] = mapped_column(String(50))
    linked_recipes_text: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    shopping_list: Mapped["ShoppingList"] = relationship(back_populates="items")
    ingredient: Mapped[Optional["Ingredient"]] = relationship(back_populates="shopping_items")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_file: Mapped[str] = mapped_column(String(500), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    issues: Mapped[list["ImportIssue"]] = relationship(back_populates="import_run", cascade="all, delete-orphan")


class ImportIssue(Base):
    __tablename__ = "import_issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    import_run_id: Mapped[int] = mapped_column(ForeignKey("import_runs.id"), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(30), nullable=False)
    sheet_name: Mapped[Optional[str]] = mapped_column(String(255))
    cell_reference: Mapped[Optional[str]] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text, nullable=False)
    raw_value: Mapped[Optional[str]] = mapped_column(Text)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    import_run: Mapped["ImportRun"] = relationship(back_populates="issues")
