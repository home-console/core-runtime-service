"""
Common DTO schemas for API responses.

ApiResponse[T] — generic envelope used by all endpoints via _normalize_api_result.
No imports from core.* allowed in this layer.
"""
from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """
    Generic response envelope: {"ok": true, "result": <payload>} on success,
    or {"ok": false, "error": "...", "code": "..."} on failure.

    `error`/`code` are part of the envelope (not of T) so that handlers can
    signal a business error — either by raising one of the typed exceptions
    in core.exceptions (caught centrally in route_binding._make_api_handler
    and turned into this shape via _normalize_api_error), or by returning
    {"ok": False, "error": ..., "code": ...} directly — without losing the
    error details to pydantic's default extra='ignore' field dropping.
    """

    ok: bool = True
    result: Optional[T] = None
    error: Optional[str] = None
    code: Optional[str] = None


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
