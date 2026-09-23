"""Client replenishment quantities composed with the multi-day route planner; no I/O."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Context, Decimal, localcontext
from fractions import Fraction
from math import ceil
from typing import Annotated, Literal, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AwareDatetime, Field, model_validator

from replenishment.planning.models import Basis, ContractModel, PositiveQuantity, Quantity, Text
from replenishment.routing import (
    DAY,
    Costs,
    Delivery,
    Recommendation,
    RoadMatrix,
    VehicleShift,
    recommend_schedule,
    validate_inputs,
)

Integer = Annotated[int, Field(ge=0, le=10_000_000, strict=True)]
Minute = Annotated[int, Field(ge=0, le=14 * DAY, strict=True)]
Day = Annotated[int, Field(ge=0, le=13, strict=True)]


class Product(ContractModel):
    product_id: Text
    supplier: Text
    sku: Text
    name: Text
    unit: Text
    warehouse_available: Quantity
    unit_weight_kg: PositiveQuantity
    unit_volume_litres: PositiveQuantity
    shipment_multiple: PositiveQuantity
    minimum_shipment: Quantity = Decimal(0)


class ClientStock(ContractModel):
    product_id: Text
    available_stock: Quantity
    reserve_units: Quantity = Decimal(0)
    daily_forecast: list[Quantity] = Field(min_length=1, max_length=14)


class Client(ContractModel):
    client_id: Text
    name: Text
    address: Text
    preferred_day: Day
    receiving_windows: list[tuple[Minute, Minute]] = Field(min_length=1, max_length=28)
    latest_delivery_minute: Minute | None = None
    locked_day: Annotated[bool, Field(strict=True)] = False
    service_minutes: Annotated[int, Field(ge=1, le=DAY, strict=True)]
    items: list[ClientStock] = Field(min_length=1, max_length=200)


class Shift(ContractModel):
    vehicle_id: Text
    day: Day
    start_minute: Minute
    end_minute: Minute
    capacity_kg: Integer
    capacity_litres: Integer
    fuel_ml_per_km: Annotated[int, Field(gt=0, le=10_000_000, strict=True)]
    activation_cost: Integer = 0


class CostPolicy(ContractModel):
    fuel_price_per_litre: Integer
    paid_cost_per_minute: Integer
    changed_day_penalty: Integer = 0


class Matrix(ContractModel):
    location_ids: list[Text] = Field(min_length=2, max_length=201)
    metres: list[Annotated[list[Integer | None], Field(max_length=201)]] = Field(max_length=201)
    minutes: list[Annotated[list[Integer | None], Field(max_length=201)]] = Field(max_length=201)
    provider: Text
    profile: Text
    captured_at: AwareDatetime

    def road(self) -> RoadMatrix:
        return RoadMatrix(tuple(map(tuple, self.metres)), tuple(map(tuple, self.minutes)))


class DeliveryPlanningRequest(ContractModel):
    input_revision: Text
    forecast_reference: Text
    inventory_reference: Text
    basis: Basis
    horizon_start: date
    horizon_days: Annotated[int, Field(ge=1, le=14, strict=True)]
    stock_as_of: date
    timezone: Text = "Asia/Almaty"
    demand_start_minute: Annotated[int, Field(ge=0, lt=DAY, strict=True)] = 0
    depot_id: Text
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] = "KZT"
    products: list[Product] = Field(min_length=1, max_length=200)
    clients: list[Client] = Field(min_length=1, max_length=200)
    shifts: list[Shift] = Field(min_length=1, max_length=100)
    costs: CostPolicy
    matrix: Matrix
    solve_time_limit_ms: Annotated[int, Field(ge=50, le=5000, strict=True)] = 1000

    def vehicle_shifts(self) -> tuple[VehicleShift, ...]:
        return tuple(VehicleShift(**shift.model_dump()) for shift in self.shifts)

    def cost_policy(self) -> Costs:
        return Costs(**self.costs.model_dump())

    @model_validator(mode="after")
    def consistent_inputs(self) -> Self:
        if self.stock_as_of != self.horizon_start:
            raise ValueError("stock_as_of must equal horizon_start; project older stock before planning")
        try:
            zone = ZoneInfo(self.timezone)
            start = datetime.combine(self.horizon_start, time(), zone)
            end = start + timedelta(days=self.horizon_days)
        except (ZoneInfoNotFoundError, ValueError, OverflowError) as error:
            raise ValueError("invalid timezone or horizon date range") from error
        if any((start + timedelta(days=day)).utcoffset() != end.utcoffset()
               for day in range(self.horizon_days)):
            raise ValueError("horizons crossing timezone offset changes are not supported")
        product_ids = {p.product_id for p in self.products}
        identities = {(p.supplier, p.sku) for p in self.products}
        if len(product_ids) != len(self.products) or len(identities) != len(self.products):
            raise ValueError("duplicate product identity")
        client_ids = {c.client_id for c in self.clients}
        if len(client_ids) != len(self.clients) or self.depot_id in client_ids:
            raise ValueError("client IDs must be unique and distinct from the depot")
        ids = self.matrix.location_ids
        if (ids[0] != self.depot_id or len(set(ids)) != len(ids)
                or set(ids) != client_ids | {self.depot_id} or len(self.matrix.metres) != len(ids)):
            raise ValueError("matrix location_ids must list the depot first and every client exactly once")
        if sum(len(c.items) for c in self.clients) > 2000:
            raise ValueError("at most 2000 client/product rows are supported")
        horizon = self.horizon_days * DAY
        for client in self.clients:
            item_ids = [item.product_id for item in client.items]
            if len(set(item_ids)) != len(item_ids) or not set(item_ids) <= product_ids:
                raise ValueError("duplicate or unknown product in client items")
            if any(len(item.daily_forecast) != self.horizon_days for item in client.items):
                raise ValueError("each daily_forecast must cover every horizon day, including explicit zeros")
            latest = client.latest_delivery_minute
            if (client.preferred_day >= self.horizon_days
                    or any(close > horizon for _, close in client.receiving_windows)
                    or (latest is not None and latest > horizon)):
                raise ValueError("client dates must be within the planning horizon")
        if any(shift.end_minute > horizon for shift in self.shifts):
            raise ValueError("vehicle shifts must be within the planning horizon")
        # Validate roads, shifts and windows even when quantities later turn out to be zero.
        validate_inputs(tuple(Delivery(
            c.client_id, ids.index(c.client_id), c.preferred_day, tuple(c.receiving_windows),
            0, horizon, c.service_minutes, 0, 0, c.locked_day,
        ) for c in self.clients), self.vehicle_shifts(), self.matrix.road(), self.cost_policy())
        return self


class ShipmentLine(ContractModel):
    product_id: str
    supplier: str
    sku: str
    name: str
    unit: str
    available_stock: Decimal
    forecast_units: Decimal
    reserve_units: Decimal
    net_need: Decimal
    quantity: Decimal
    rounding_surplus: Decimal
    latest_safe_minute: int | None


class ClientRecommendation(ContractModel):
    client_id: str
    name: str
    address: str
    status: Literal["no_delivery_needed", "pending", "blocked", "planned"]
    items: list[ShipmentLine]
    preferred_date: date
    recommended_date: date | None = None
    vehicle_id: str | None = None
    service_start_minute: int | None = None
    service_end_minute: int | None = None
    latest_safe_minute: int | None = None
    weight_kg: int = 0
    volume_litres: int = 0
    reason: str


class PlanningIssue(ContractModel):
    code: str
    message: str
    client_id: str | None = None
    product_id: str | None = None


class DeliveryPlanningResult(ContractModel):
    input_revision: str
    forecast_reference: str
    inventory_reference: str
    basis: Basis
    horizon_start: date
    horizon_days: int
    timezone: str
    currency: str
    status: Literal["ready_for_review", "no_delivery_needed", "blocked", "no_feasible_plan"]
    clients: list[ClientRecommendation]
    issues: list[PlanningIssue]
    routing: Recommendation | None = None
    warnings: list[str]


def recommend_deliveries(request: DeliveryPlanningRequest) -> DeliveryPlanningResult:
    """One shipment per client, sized to cover the entire supplied forecast horizon."""
    # Fixed Decimal context keeps quantity/weight arithmetic independent of callers.
    with localcontext(Context(prec=100)):
        return _recommend(request)


def _recommend(request: DeliveryPlanningRequest) -> DeliveryPlanningResult:
    products = {p.product_id: p for p in request.products}
    allocated = defaultdict(Decimal)
    deliveries, clients, issues = [], [], []
    horizon = request.horizon_days * DAY
    for client in request.clients:
        lines, weight, volume, deadlines = [], Decimal(0), Decimal(0), [horizon]
        if client.latest_delivery_minute is not None:
            deadlines.append(client.latest_delivery_minute)
        for item in client.items:
            product = products[item.product_id]
            forecast = sum(item.daily_forecast, Decimal(0))
            need = max(Decimal(0), forecast + item.reserve_units - item.available_stock)
            packs = ceil(Fraction(max(need, product.minimum_shipment)) / Fraction(product.shipment_multiple))
            quantity = packs * product.shipment_multiple if need else Decimal(0)
            remaining, deadline = item.available_stock, None
            if remaining < item.reserve_units:
                deadline = 0
            for day, units in enumerate(item.daily_forecast):
                remaining -= units
                if deadline is None and remaining < item.reserve_units:
                    deadline = day * DAY + request.demand_start_minute
            if quantity and deadline is not None:
                deadlines.append(deadline)
            allocated[product.product_id] += quantity
            weight += quantity * product.unit_weight_kg
            volume += quantity * product.unit_volume_litres
            lines.append(ShipmentLine(
                product_id=product.product_id, supplier=product.supplier, sku=product.sku, name=product.name,
                unit=product.unit, available_stock=item.available_stock, forecast_units=forecast,
                reserve_units=item.reserve_units, net_need=need, quantity=quantity,
                rounding_surplus=quantity - need, latest_safe_minute=deadline,
            ))
        needed = any(line.quantity for line in lines)
        latest = min(deadlines) if needed else None
        clients.append(ClientRecommendation(
            client_id=client.client_id, name=client.name, address=client.address,
            status="pending" if needed else "no_delivery_needed", items=lines,
            preferred_date=request.horizon_start + timedelta(days=client.preferred_day),
            latest_safe_minute=latest, weight_kg=ceil(weight), volume_litres=ceil(volume),
            reason="awaiting_route" if needed else "stock_covers_forecast_and_reserve",
        ))
        if needed:
            deliveries.append(Delivery(
                client.client_id, request.matrix.location_ids.index(client.client_id), client.preferred_day,
                tuple(client.receiving_windows), 0, latest, client.service_minutes,
                ceil(weight), ceil(volume), client.locked_day,
            ))
    for product_id, quantity in allocated.items():
        available = products[product_id].warehouse_available
        if quantity > available:
            issues.append(PlanningIssue(
                code="warehouse_shortage", product_id=product_id,
                message=f"Required {quantity} {products[product_id].unit}; available to ship {available}.",
            ))
    result = DeliveryPlanningResult(
        input_revision=request.input_revision, forecast_reference=request.forecast_reference,
        inventory_reference=request.inventory_reference, basis=request.basis,
        horizon_start=request.horizon_start, horizon_days=request.horizon_days, timezone=request.timezone,
        currency=request.currency, status="blocked" if issues else "no_delivery_needed",
        clients=clients, issues=issues,
        warnings=[
            "Recommendation only; inventory is not reserved and deliveries are not dispatched.",
            "Uses supplied client forecasts and opening stock; "
            "warehouse stock must be available at departure.",
            "One shipment per client; other customer receipts, "
            "storage limits and driver breaks are not modeled.",
            f"Shared road matrix: {request.matrix.provider}, {request.matrix.profile}, "
            f"captured {request.matrix.captured_at.isoformat()}; no departure-time traffic adjustment.",
        ],
    )
    if deliveries and not issues:
        routing = recommend_schedule(tuple(deliveries), request.vehicle_shifts(), request.matrix.road(),
                                     request.cost_policy(), time_limit_ms=request.solve_time_limit_ms)
        result.routing = routing
        if routing.proposed.cost is None:
            result.status = "no_feasible_plan"
            result.issues.append(PlanningIssue(
                code="no_complete_route_found",
                message="No complete plan found within the search budget and supplied constraints; "
                        "review stock deadlines, receiving windows, road reachability and vehicle capacity.",
            ))
        else:
            result.status = "ready_for_review"
            by_id = {c.client_id: c for c in clients}
            changes = {c.delivery_id: c.reason for c in routing.changes}
            for route in routing.proposed.routes:
                for visit in route.visits:
                    client = by_id[visit.delivery_id]
                    client.status = "planned"
                    client.recommended_date = request.horizon_start + timedelta(days=route.day)
                    client.vehicle_id = route.vehicle_id
                    client.service_start_minute = visit.service_start_minute
                    client.service_end_minute = visit.service_end_minute
                    client.reason = changes.get(client.client_id, "preferred_day_retained")
    for client in clients:
        if client.status == "pending":
            client.status = "blocked"
            client.reason = "warehouse_shortage" if issues else "no_complete_route_found"
    return result
