"""User management schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, field_validator


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    password: str | None = None


class UpdateUserRoleRequest(BaseModel):
    role: str


# ---- Admin CRUD ----

class AdminCreateUserRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None
    role: str = "trader"


class AdminUpdateUserRequest(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None


class AdminResetPasswordRequest(BaseModel):
    new_password: str


class BanUserRequest(BaseModel):
    reason: str


# ---- Detailed user response for admin views ----

class UserDetailResponse(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str | None
    role: str
    is_active: bool
    ban_reason: str | None
    banned_at: datetime | None
    banned_by: uuid.UUID | None
    last_login_at: datetime | None
    failed_login_count: int
    locked_until: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ---- Login activity ----

class LoginActivityResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    email: str
    ip_address: str | None
    user_agent: str | None
    country: str | None
    city: str | None
    success: bool
    failure_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("ip_address", mode="before")
    @classmethod
    def coerce_ip(cls, v: Any) -> str | None:
        if v is None:
            return None
        return str(v)

