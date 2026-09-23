"""HTTP composition of the pure calculator and transactional order workflow."""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Engine
from sqlalchemy.exc import SQLAlchemyError

from replenishment.orders import writing
from replenishment.planning.calculator import calculate
from replenishment.planning.demo import demo_cases
from replenishment.planning.models import PlanningRequest, PlanningResult

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Override(Payload):
    row_id: Annotated[str, StringConstraints(min_length=1)]
    quantity: Annotated[Decimal, Field(ge=0, allow_inf_nan=False)]
    reason: Reason


class CreateScenario(Payload):
    name: Name
    input: PlanningRequest


class UpdateScenario(CreateScenario):
    expected_revision: Annotated[int, Field(ge=1)]
    overrides: list[Override] = Field(default_factory=list, max_length=200)


class ApproveScenario(Payload):
    expected_revision: Annotated[int, Field(ge=1)]
    approved_by: Name
    acknowledge_scenario: bool = False


class ScenarioDetail(BaseModel):
    id: UUID
    name: str
    revision: int
    input: PlanningRequest
    result: PlanningResult
    overrides: list[Override]
    approved_revision: int | None
    approved_by: str | None
    approved_at: datetime | None
    updated_at: datetime


def _run(command, *args, **kwargs):
    try:
        return command(*args, **kwargs)
    except writing.ScenarioNotFound as error:
        raise HTTPException(404, str(error)) from error
    except writing.ScenarioConflict as error:
        raise HTTPException(409, str(error)) from error
    except writing.InvalidScenario as error:
        raise HTTPException(422, str(error)) from error
    except SQLAlchemyError as error:
        raise HTTPException(503, "Database unavailable") from error


def create_orders_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix="/api/v1")

    @router.get("/planning/demo-cases")
    def examples():
        return demo_cases()

    @router.post("/planning/calculate", response_model=PlanningResult)
    def preview(payload: PlanningRequest):
        return calculate(payload)

    @router.get("/scenarios")
    def scenarios():
        return _run(writing.list_scenarios, engine)

    @router.post("/scenarios", response_model=ScenarioDetail, status_code=201)
    def create(payload: CreateScenario):
        return _run(writing.create_scenario, engine, name=payload.name,
                    input=payload.input.model_dump(mode="json"),
                    result=calculate(payload.input).model_dump(mode="json"))

    @router.get("/scenarios/{scenario_id}", response_model=ScenarioDetail)
    def get(scenario_id: UUID):
        return _run(writing.get_scenario, engine, scenario_id)

    @router.put("/scenarios/{scenario_id}", response_model=ScenarioDetail)
    def update(scenario_id: UUID, payload: UpdateScenario):
        return _run(writing.update_scenario, engine, scenario_id, expected_revision=payload.expected_revision,
                    name=payload.name, input=payload.input.model_dump(mode="json"),
                    result=calculate(payload.input).model_dump(mode="json"),
                    overrides=[item.model_dump(mode="json") for item in payload.overrides])

    @router.post("/scenarios/{scenario_id}/approve", response_model=ScenarioDetail)
    def approve(scenario_id: UUID, payload: ApproveScenario):
        return _run(writing.approve_scenario, engine, scenario_id, **payload.model_dump())

    @router.get("/scenarios/{scenario_id}/export")
    def export(scenario_id: UUID, expected_revision: Annotated[int, Query(ge=1)]):
        content = _run(writing.export_scenario, engine, scenario_id, expected_revision=expected_revision)
        return Response(content=content.encode("utf-8-sig"), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="scenario-{scenario_id}-r{expected_revision}.csv"',
        })

    return router
