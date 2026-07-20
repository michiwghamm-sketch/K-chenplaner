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
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    aliases: Mapped[list["IngredientAlias"]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")
    prices: Mapped[list["IngredientPrice"]] = relationship(back_populates="ingredient", cascade="all, delete-orphan")
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
    price_per_unit: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
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


class Recipe(Base):
    __tablename__ = "recipes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100))
    meal_type: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    default_portions: Mapped[Optional[int]] = mapped_column(Integer)
    instructions: Mapped[Optional[str]] = mapped_column(Text)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = created_timestamp_column()
    updated_at: Mapped[datetime] = updated_timestamp_column()

    ingredients: Mapped[list["RecipeIngredient"]] = relationship(back_populates="recipe", cascade="all, delete-orphan")
    meal_plan_entries: Mapped[list["MealPlanEntry"]] = relationship(back_populates="recipe")
    feedback_entries: Mapped[list["RecipeFeedback"]] = relationship(back_populates="recipe")


class RecipeIngredient(Base):
    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe_id: Mapped[int] = mapped_column(ForeignKey("recipes.id"), nullable=False, index=True)
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(50), nullable=False)
    price_unit: Mapped[Optional[str]] = mapped_column(String(50))
    optional: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)

    recipe: Mapped["Recipe"] = relationship(back_populates="ingredients")
    ingredient: Mapped["Ingredient"] = relationship(back_populates="recipe_links")


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
    estimated_price_per_unit: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    estimated_total_price: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    category: Mapped[Optional[str]] = mapped_column(String(100))
    storage_type: Mapped[Optional[str]] = mapped_column(String(100))
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
