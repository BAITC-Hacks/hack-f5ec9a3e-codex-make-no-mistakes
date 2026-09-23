"""Stateless recommendations for what to send to clients and when."""

from fastapi import APIRouter, HTTPException

from replenishment.delivery_planning import (
    DeliveryPlanningRequest,
    DeliveryPlanningResult,
    recommend_deliveries,
)
from replenishment.delivery_planning_demo import almaty_demo_input

router = APIRouter(prefix="/api/v1/delivery-planning", tags=["Client delivery planning"])


@router.get("/demo-input", response_model=DeliveryPlanningRequest)
def demo_input():
    try:
        return almaty_demo_input()
    except (OSError, ValueError, KeyError) as error:
        raise HTTPException(503, "Almaty demo fixtures unavailable or inconsistent") from error


@router.post("/recommend", response_model=DeliveryPlanningResult)
def recommend(payload: DeliveryPlanningRequest):
    try:
        return recommend_deliveries(payload)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
