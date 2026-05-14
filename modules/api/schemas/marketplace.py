"""Marketplace DTO schemas."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class MarketplaceCatalogEntryDto(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    repo_url: str
    version: Optional[str] = None
    dependencies: Optional[List[str]] = None


class InstalledPluginDto(BaseModel):
    name: str
    version: Optional[str] = None
    enabled: Optional[bool] = None
    source: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class MarketplaceResultDto(BaseModel):
    ok: bool = True
    plugin_name: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class GitSourcesDto(BaseModel):
    sources: List[str] = []


class GitCatalogEntryDto(BaseModel):
    name: str
    source: str
    version: Optional[str] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# --- Request models ---


class InstallFromArchiveRequest(BaseModel):
    url: Optional[str] = None
    plugin_name: Optional[str] = None


class InstallFromRegistryRequest(BaseModel):
    plugin_name: str
    version: Optional[str] = None
    registry_url: Optional[str] = None


class InstallFromGitRequest(BaseModel):
    repo_url: str
    plugin_name: Optional[str] = None
    branch: Optional[str] = None
    tag: Optional[str] = None


class RemovePluginRequest(BaseModel):
    plugin_name: str


class UpdatePluginRequest(BaseModel):
    plugin_name: str
    version: Optional[str] = None


class SetGitSourcesRequest(BaseModel):
    sources: List[str]


class BuildGitCatalogRequest(BaseModel):
    sources: Optional[List[str]] = None
