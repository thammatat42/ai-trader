"""
User management API – profile, update, admin user list.
"""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user, require_role
from app.core.exceptions import NotFoundError
from app.core.security import hash_password
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.user import UpdateProfileRequest, UpdateUserRoleRequest

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.put("/me", response_model=UserResponse)
async def update_me(
    body: UpdateProfileRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.password is not None:
        user.hashed_password = hash_password(body.password)
    await db.commit()
    await db.refresh(user)
    return user


# ---- Admin-only endpoints ----

@router.get("", response_model=list[UserResponse])
async def list_users(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.put("/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: str,
    body: UpdateUserRoleRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise NotFoundError("User")

    target_user.role = body.role
    await db.commit()
    await db.refresh(target_user)
    return target_user


@router.put("/{user_id}/deactivate", response_model=UserResponse)
async def deactivate_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise NotFoundError("User")

    target_user.is_active = False
    await db.commit()
    await db.refresh(target_user)
    return target_user
