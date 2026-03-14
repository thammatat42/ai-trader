"""User management schemas."""

from pydantic import BaseModel


class UpdateProfileRequest(BaseModel):
    full_name: str | None = None
    password: str | None = None


class UpdateUserRoleRequest(BaseModel):
    role: str
