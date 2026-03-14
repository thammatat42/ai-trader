"""Common schemas used across the API."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    version: str
    environment: str
    db: bool
    redis: bool


class MessageResponse(BaseModel):
    message: str


class ErrorResponse(BaseModel):
    detail: str


class PaginationParams(BaseModel):
    page: int = 1
    per_page: int = 20


class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int
