"""API v1 router."""

from fastapi import APIRouter

from backend.api.v1.endpoints import agents
from workflows import endpoints as workflow

api_router = APIRouter()

api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(workflow.router, prefix="/workflow", tags=["workflow"])