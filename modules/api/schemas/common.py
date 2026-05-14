"""
Common DTO schemas for API responses.

ApiResponse[T] — generic envelope used by all endpoints via _normalize_api_result.
No imports from core.* allowed in this layer.
"""
from __future__ import annotations

from typing import Generic, List, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Generic response envelope: {"ok": true, "result": <payload>}."""

    ok: bool = True
    result: Optional[T] = None


class OkResponse(BaseModel):
    """Plain success response: {"ok": true}."""

    ok: bool = True


class OkErrorResponse(BaseModel):
    """Success-or-failure response with optional error message."""

    ok: bool
    error: Optional[str] = None
    message: Optional[str] = None


class DeletedResponse(BaseModel):
    ok: bool = True
    deleted: bool = True
