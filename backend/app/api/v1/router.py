"""
API v1 – aggregate all sub-routers.
"""

from fastapi import APIRouter

from app.api.v1.auth import api_keys_router, router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.plans import admin_plans_router, credits_router, router as plans_router, subscriptions_router
from app.api.v1.platforms import router as platforms_router
from app.api.v1.trades import router as trades_router
from app.api.v1.users import router as users_router
from app.api.v1.ws import router as ws_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(health_router)
v1_router.include_router(auth_router)
v1_router.include_router(api_keys_router)
v1_router.include_router(users_router)
v1_router.include_router(plans_router)
v1_router.include_router(subscriptions_router)
v1_router.include_router(credits_router)
v1_router.include_router(admin_plans_router)
v1_router.include_router(trades_router)
v1_router.include_router(platforms_router)
v1_router.include_router(ws_router)
