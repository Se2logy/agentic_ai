"""Main API router — aggregates all endpoint routers under /api/v1."""

from fastapi import APIRouter

from app.api.audit import router as audit_router
from app.api.id_upload import router as id_upload_router
from app.api.incidental import router as incidental_router
from app.api.otp import router as otp_router
from app.api.reservations import router as reservations_router
from app.api.sessions import router as sessions_router
from app.api.websocket import router as websocket_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(sessions_router)
api_router.include_router(reservations_router)
api_router.include_router(otp_router)
api_router.include_router(id_upload_router)
api_router.include_router(incidental_router)
api_router.include_router(audit_router)
api_router.include_router(websocket_router)
