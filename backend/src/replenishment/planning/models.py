"""Shared planning contract. Decimal quantities serialize as JSON strings."""

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Quantity = Annotated[Decimal, Field(ge=0, allow_inf_nan=False, max_digits=30, decimal_places=12)]
PositiveQuantity = Annotated[Decimal, Field(gt=0, allow_inf_nan=False, max_digits=30, decimal_places=12)]
Growth = Annotated[Decimal, Field(gt=-100, allow_inf_nan=False, max_digits=30, decimal_places=12)]
LeadDays = Annotated[int, Field(ge=0, le=365, strict=True)]
Text = Annotated[str, Field(min_length=1, max_length=500)]
Basis = Literal["observed", "assumed", "synthetic"]
Seasonality = dict[Annotated[str, Field(pattern=r"^(?:[1-9]|1[0-2])$")], Quantity]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceRef(ContractModel):
    label: Text
    source_row_id: str | None = None
    workbook_id: str | None = None
    normalizer_version: str | None = None


class Sale(ContractModel):
    day: date
    quantity: Quantity
    document: Text
    customer_id: Text | None = None


class Incoming(ContractModel):
    id: Text
    quantity: Quantity | None = None
    expected_on: date | None = None
    warehouse: Text | None = None
    stock_unit: Text | None = None


class InputRow(ContractModel):
    row_id: Text
    supplier: Text
    sku: Text
    name: str
    stock_unit: Text
    warehouse: Text | None = None
    purchase_unit: Text | None = None
    free_stock: Quantity | None = None
    stock_as_of: date | None = None
    stock_scope_confirmed: bool = False
    incoming_complete: bool = False
    constraints_confirmed: bool = False
    stock_per_purchase_unit: PositiveQuantity | None = None
    minimum_order: Quantity | None = None
    order_multiple: PositiveQuantity | None = None
    lead_time_days: LeadDays | None = None
    buffer_days: Quantity | None = None
    growth_pct: Growth | None = None
    category: str | None = None
    seasonality: Seasonality | None = None
    daily_demand: Quantity | None = None
    history_start: date | None = None
    history_end: date | None = None
    sales: list[Sale] = Field(default_factory=list, max_length=100000)
    stockout_days: list[date] = Field(default_factory=list, max_length=3660)
    incoming: list[Incoming] = Field(default_factory=list, max_length=10000)
    basis: Basis = "assumed"
    notes: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_history_and_shipments(self) -> Self:
        if len({item.id for item in self.incoming}) != len(self.incoming):
            raise ValueError("Duplicate incoming shipment identity; reconcile before calculating")
        if len(set(self.stockout_days)) != len(self.stockout_days):
            raise ValueError("Duplicate stockout day")
        if self.history_start and self.history_end:
            if self.history_start > self.history_end:
                raise ValueError("history_start must be on or before history_end")
            if (self.history_end - self.history_start).days > 3659:
                raise ValueError("History window must contain at most 3660 days")
        for day in [sale.day for sale in self.sales] + self.stockout_days:
            if self.history_start and day < self.history_start:
                raise ValueError("Sales and stockout dates must be inside the declared history window")
            if self.history_end and day > self.history_end:
                raise ValueError("Sales and stockout dates must be inside the declared history window")
        return self


class PlanningRequest(ContractModel):
    planning_date: date
    lead_time_days: LeadDays | None = None
    review_days: Annotated[int, Field(ge=1, le=365, strict=True)] = 7
    buffer_days: Quantity = Decimal(0)
    growth_pct: Growth = Decimal(0)
    seasonality: Seasonality = Field(default_factory=dict)
    category_buffer_days: dict[Text, Quantity] = Field(default_factory=dict)
    exclude_bulk: bool = False
    compensate_stockouts: bool = False
    rows: list[InputRow] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_rows_and_forecast_origin(self) -> Self:
        if len({row.row_id for row in self.rows}) != len(self.rows):
            raise ValueError("Duplicate row_id")
        keys = [(row.supplier, row.sku, row.warehouse, row.stock_unit) for row in self.rows]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate supplier/SKU/warehouse/stock-unit row")
        for row in self.rows:
            if row.history_end and row.history_end >= self.planning_date:
                raise ValueError("history_end must be strictly before planning_date")
            if row.history_start and row.history_start >= self.planning_date:
                raise ValueError("history_start must be strictly before planning_date")
            if any(sale.day >= self.planning_date for sale in row.sales):
                raise ValueError("Sales on or after planning_date cannot be used as forecast evidence")
            if any(day >= self.planning_date for day in row.stockout_days):
                raise ValueError("Stockout evidence must be strictly before planning_date")
            lead = row.lead_time_days if row.lead_time_days is not None else self.lead_time_days
            try:
                self.planning_date + timedelta(days=(lead or 0) + self.review_days)
            except OverflowError as error:
                raise ValueError("Coverage end is outside the supported date range") from error
        return self


class IncomingDecision(ContractModel):
    id: str
    credited: bool
    quantity: Decimal | None
    reason: str


class DailyBalance(ContractModel):
    day: date
    demand: Decimal
    incoming: Decimal
    balance: Decimal


class ResultRow(ContractModel):
    row_id: str
    supplier: str
    sku: str
    name: str
    stock_unit: str
    purchase_unit: str | None
    basis: Basis
    status: Literal["needs_input", "scenario_only", "ready_for_review"]
    missing_inputs: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    explanation: str
    daily_demand: Decimal | None = None
    raw_daily_demand: Decimal | None = None
    excluded_bulk_quantity: Decimal | None = None
    lost_demand_quantity: Decimal | None = None
    forecast_demand: Decimal | None = None
    buffer: Decimal | None = None
    free_stock: Decimal | None = None
    eligible_incoming: Decimal | None = None
    raw_need: Decimal | None = None
    recommended_quantity: Decimal | None = None
    stock_equivalent: Decimal | None = None
    rounding_surplus: Decimal | None = None
    maximum_prearrival_shortfall: Decimal | None = None
    coverage_end: date | None = None
    arrival_date: date | None = None
    first_shortage_date: date | None = None
    incoming_decisions: list[IncomingDecision] = Field(default_factory=list)
    daily_balances: list[DailyBalance] = Field(default_factory=list)
    demand_adjustments: list[str] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)


class PlanningResult(ContractModel):
    planning_date: date
    rows: list[ResultRow]
    warnings: list[str] = Field(default_factory=list)
