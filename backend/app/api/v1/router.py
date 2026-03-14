"""
API v1 – aggregate all sub-routers.
"""

from fastapi import APIRouter

from app.api.v1.auth import api_keys_router, router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.users import router as users_router
from app.api.v1.ws import router as ws_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(health_router)
v1_router.include_router(auth_router)
v1_router.include_router(api_keys_router)
v1_router.include_router(users_router)
v1_router.include_router(ws_router)
