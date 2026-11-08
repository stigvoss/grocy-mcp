"""Stable workflow-oriented data contracts for preview/apply flows."""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from grocy_mcp.core.utils import is_iso_date


def _normalize_optional_text(value: str | None) -> str | None:
    """Collapse whitespace and normalize empty strings to None."""
    if value is None:
        return None
    normalized = " ".join(value.strip().split())
    return normalized or None


class WorkflowPreviewCandidate(BaseModel):
    product_id: int
    name: str

    model_config = {"extra": "forbid"}


class WorkflowNormalizedInputItem(BaseModel):
    label: str
    quantity: float = 1.0
    unit_text: str | None = None
    barcode: str | None = None
    note: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        normalized = " ".join(value.strip().split())
        if not normalized:
            raise ValueError("label must not be empty")
        return normalized

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("quantity must be greater than 0")
        return value

    @field_validator("unit_text", "barcode", "note")
    @classmethod
    def normalize_optional_fields(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)


class WorkflowMatchPreviewItem(BaseModel):
    input_index: int
    label: str
    status: Literal["matched", "ambiguous", "unmatched"]
    matched_product_id: int | None = None
    matched_product_name: str | None = None
    candidates: list[WorkflowPreviewCandidate] = Field(default_factory=list)
    suggested_amount: float
    unit_text: str | None = None

    model_config = {"extra": "forbid"}


class WorkflowApplyItem(BaseModel):
    product_id: int
    amount: float
    note: str | None = None
    price: float | None = Field(default=None, allow_inf_nan=False)
    best_before_date: str | None = None
    location_id: int | None = None
    purchased_date: str | None = None
    shopping_location_id: int | None = None

    model_config = {"extra": "forbid"}

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("amount must be greater than 0")
        return value

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        return _normalize_optional_text(value)

    @field_validator("price")
    @classmethod
    def validate_price(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("price must not be negative")
        return value

    @field_validator("best_before_date", "purchased_date")
    @classmethod
    def validate_iso_date(cls, value: str | None, info: ValidationInfo) -> str | None:
        value = _normalize_optional_text(value)
        if value is not None and not is_iso_date(value):
            raise ValueError(f"{info.field_name} must be formatted as YYYY-MM-DD")
        return value


class WorkflowShoppingReconcilePreviewAction(BaseModel):
    shopping_item_id: int
    action: Literal["remove", "set_amount"]
    previous_amount: float
    new_amount: float | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_action(self) -> WorkflowShoppingReconcilePreviewAction:
        if self.action == "set_amount":
            if self.new_amount is None:
                raise ValueError("new_amount is required when action is set_amount")
            if self.new_amount <= 0:
                raise ValueError("new_amount must be greater than 0 when action is set_amount")
        return self


class WorkflowShoppingReconcilePreviewItem(BaseModel):
    input_index: int
    product_id: int
    purchased_amount: float
    status: Literal["matched", "partial", "unmatched"]
    actions: list[WorkflowShoppingReconcilePreviewAction] = Field(default_factory=list)
    unapplied_amount: float = 0

    model_config = {"extra": "forbid"}


class WorkflowShoppingReconcileApplyAction(BaseModel):
    shopping_item_id: int
    action: Literal["remove", "set_amount"]
    new_amount: float | None = None
    # Emitted by the preview; accepted so preview actions can be passed straight to apply.
    previous_amount: float | None = Field(default=None, exclude=True)

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_action(self) -> WorkflowShoppingReconcileApplyAction:
        if self.action == "set_amount":
            if self.new_amount is None:
                raise ValueError("new_amount is required when action is set_amount")
            if self.new_amount <= 0:
                raise ValueError("new_amount must be greater than 0 when action is set_amount")
        return self


def _finite_positive(value: float) -> float:
    if not (math.isfinite(value) and value > 0):
        raise ValueError("must be a finite number greater than 0")
    return value


class _StockActionBase(BaseModel):
    product: str

    model_config = {"extra": "forbid"}

    @field_validator("product", mode="before")
    @classmethod
    def product_as_text(cls, value: object) -> object:
        return str(value) if isinstance(value, int) and not isinstance(value, bool) else value

    @field_validator("product")
    @classmethod
    def product_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("product must not be blank")
        return value.strip()


class StockConsumeAction(_StockActionBase):
    action: Literal["consume"]
    amount: float
    from_location: str | None = None
    spoiled: bool = False

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, value: float) -> float:
        return _finite_positive(value)


class StockOpenAction(_StockActionBase):
    action: Literal["open"]
    amount: float = 1.0

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, value: float) -> float:
        return _finite_positive(value)


class StockInventoryAction(_StockActionBase):
    action: Literal["inventory"]
    new_amount: float
    opened_amount: float | None = None

    @field_validator("new_amount")
    @classmethod
    def new_amount_not_negative(cls, value: float) -> float:
        if not (math.isfinite(value) and value >= 0):
            raise ValueError("must be a finite number that is not negative")
        return value


class StockTransferAction(_StockActionBase):
    action: Literal["transfer"]
    amount: float
    to_location: str
    from_location: str | None = None

    @field_validator("amount")
    @classmethod
    def amount_positive(cls, value: float) -> float:
        return _finite_positive(value)


StockAction = Annotated[
    StockConsumeAction | StockOpenAction | StockInventoryAction | StockTransferAction,
    Field(discriminator="action"),
]
