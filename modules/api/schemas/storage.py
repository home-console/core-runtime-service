"""Storage DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class StorageNamespaceDto(BaseModel):
    namespace: str
    keys_count: Optional[int] = None
    restricted: Optional[bool] = None
    debug_decrypted: Optional[bool] = None
    entries: Optional[Dict[str, Any]] = None


class StorageNamespaceContentsDto(BaseModel):
    namespace: str
    keys: List[str] = []
    entries: Dict[str, Any] = {}
    restricted: Optional[bool] = None
    debug_decrypted: Optional[bool] = None
    message: Optional[str] = None
    error: Optional[str] = None
