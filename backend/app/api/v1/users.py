"""
User management API – profile, admin CRUD, ban/unban, password reset, login activity.
"""

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user, require_role
from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.security import hash_password
from app.models.login_activity import LoginActivity
from app.models.user import User
from app.schemas.auth import UserResponse
from app.schemas.user import (
    AdminCreateUserRequest,
    AdminResetPasswordRequest,
    AdminUpdateUserRequest,
    BanUserRequest,
    LoginActivityResponse,
    UpdateProfileRequest,
    UpdateUserRoleRequest,
    UserDetailResponse,
)

router = APIRouter(prefix="/users", tags=["users"])

VALID_ROLES = {"admin", "trader", "viewer"}


# ---- Self-service ----

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


# ---- Admin: User CRUD ----

@router.get("", response_model=list[UserDetailResponse])
async def list_users(
    search: str | None = Query(None, description="Search by email or name"),
    role: str | None = Query(None, description="Filter by role"),
    status: str | None = Query(None, description="Filter: active, inactive, banned, locked"),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    query = select(User).order_by(User.created_at.desc())

    if search:
        pattern = f"%{search}%"
        query = query.where(
            or_(User.email.ilike(pattern), User.full_name.ilike(pattern))
        )
    if role and role in VALID_ROLES:
        query = query.where(User.role == role)
    if status == "active":
        query = query.where(User.is_active.is_(True), User.banned_at.is_(None))
    elif status == "inactive":
        query = query.where(User.is_active.is_(False))
    elif status == "banned":
        query = query.where(User.banned_at.isnot(None))
    elif status == "locked":
        query = query.where(User.locked_until > datetime.now(timezone.utc))

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/login-activity", response_model=list[LoginActivityResponse])
async def list_all_login_activity(
    limit: int = Query(50, ge=1, le=200),
    success: bool | None = Query(None),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """List all login activity across all users (admin only)."""
    query = select(LoginActivity).order_by(LoginActivity.created_at.desc()).limit(limit)
    if success is not None:
        query = query.where(LoginActivity.success == success)
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{user_id}", response_model=UserDetailResponse)
async def get_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Get detailed info about a single user."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")
    return target


@router.post("", response_model=UserDetailResponse, status_code=201)
async def create_user(
    body: AdminCreateUserRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin creates a new user."""
    if body.role not in VALID_ROLES:
        raise ValidationError(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise ConflictError("Email already registered")

    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/{user_id}", response_model=UserDetailResponse)
async def update_user(
    user_id: str,
    body: AdminUpdateUserRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin updates a user's profile fields."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")

    if body.email is not None and body.email != target.email:
        dup = await db.execute(select(User).where(User.email == body.email))
        if dup.scalar_one_or_none():
            raise ConflictError("Email already in use")
        target.email = body.email
    if body.full_name is not None:
        target.full_name = body.full_name
    if body.role is not None:
        if body.role not in VALID_ROLES:
            raise ValidationError(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")
        target.role = body.role
    if body.is_active is not None:
        target.is_active = body.is_active

    await db.commit()
    await db.refresh(target)
    return target


@router.delete("/{user_id}")
async def delete_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Deactivate a user (soft delete). Admins cannot delete themselves."""
    if str(admin.id) == user_id:
        raise ForbiddenError("Cannot delete your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")

    target.is_active = False
    await db.commit()
    return {"message": "User deactivated"}


# ---- Admin: Role ----

@router.put("/{user_id}/role", response_model=UserDetailResponse)
async def update_user_role(
    user_id: str,
    body: UpdateUserRoleRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    if body.role not in VALID_ROLES:
        raise ValidationError(f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}")

    result = await db.execute(select(User).where(User.id == user_id))
    target_user = result.scalar_one_or_none()
    if not target_user:
        raise NotFoundError("User")

    target_user.role = body.role
    await db.commit()
    await db.refresh(target_user)
    return target_user


# ---- Admin: Activate / Deactivate ----

@router.put("/{user_id}/deactivate", response_model=UserDetailResponse)
async def deactivate_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    if str(admin.id) == user_id:
        raise ForbiddenError("Cannot deactivate your own account")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")
    target.is_active = False
    await db.commit()
    await db.refresh(target)
    return target


@router.put("/{user_id}/activate", response_model=UserDetailResponse)
async def activate_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")
    target.is_active = True
    await db.commit()
    await db.refresh(target)
    return target


# ---- Admin: Password Reset ----

@router.post("/{user_id}/reset-password")
async def admin_reset_password(
    user_id: str,
    body: AdminResetPasswordRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin resets a user's password to a specified value."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")

    target.hashed_password = hash_password(body.new_password)
    target.failed_login_count = 0
    target.locked_until = None
    await db.commit()
    return {"message": "Password has been reset"}


# ---- Admin: Ban / Unban ----

@router.post("/{user_id}/ban", response_model=UserDetailResponse)
async def ban_user(
    user_id: str,
    body: BanUserRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Ban a user with a reason. Immediately revokes all access."""
    if str(admin.id) == user_id:
        raise ForbiddenError("Cannot ban your own account")

    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")
    if target.is_banned:
        raise ValidationError("User is already banned")

    target.ban_reason = body.reason
    target.banned_at = datetime.now(timezone.utc)
    target.banned_by = admin.id
    target.is_active = False
    await db.commit()
    await db.refresh(target)
    return target


@router.post("/{user_id}/unban", response_model=UserDetailResponse)
async def unban_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Unban a user and reactivate their account."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")
    if not target.is_banned:
        raise ValidationError("User is not banned")

    target.ban_reason = None
    target.banned_at = None
    target.banned_by = None
    target.is_active = True
    target.failed_login_count = 0
    target.locked_until = None
    await db.commit()
    await db.refresh(target)
    return target


# ---- Admin: Unlock ----

@router.post("/{user_id}/unlock", response_model=UserDetailResponse)
async def unlock_user(
    user_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Unlock a locked account and reset failed login counter."""
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")

    target.failed_login_count = 0
    target.locked_until = None
    await db.commit()
    await db.refresh(target)
    return target


# ---- Admin: Login Activity per user ----

@router.get("/{user_id}/login-activity", response_model=list[LoginActivityResponse])
async def get_user_login_activity(
    user_id: str,
    limit: int = Query(50, ge=1, le=200),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """View login activity for a specific user."""
    result = await db.execute(select(User).where(User.id == user_id))
    if not result.scalar_one_or_none():
        raise NotFoundError("User")

    query = (
        select(LoginActivity)
        .where(LoginActivity.user_id == user_id)
        .order_by(LoginActivity.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()
