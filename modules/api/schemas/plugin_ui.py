"""Server-driven UI contributions from plugin.json (not arbitrary JS modules)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class UiPageContributionDto(BaseModel):
    path: str
    type: Optional[str] = None
    module: Optional[str] = None
    title: Optional[str] = None
    service: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    config_schema: Optional[Dict[str, Any]] = None


class UiWidgetContributionDto(BaseModel):
    id: str
    type: Optional[str] = None
    module: Optional[str] = None
    title: Optional[str] = None
    service: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    config_schema: Optional[Dict[str, Any]] = None


class PluginUiContributionsDto(BaseModel):
    plugin_name: str
    plugin_version: Optional[str] = None
    on_disk: bool = False
    loaded: bool = False
    pages: List[UiPageContributionDto] = Field(default_factory=list)
    widgets: List[UiWidgetContributionDto] = Field(default_factory=list)
    dashboard_cards: List[UiWidgetContributionDto] = Field(default_factory=list)


class DashboardCardDto(BaseModel):
    """Flattened dashboard card from a plugin manifest (server-driven only)."""

    plugin_name: str
    plugin_version: Optional[str] = None
    id: str
    type: Optional[str] = None
    module: Optional[str] = None
    title: Optional[str] = None
    service: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    config_schema: Optional[Dict[str, Any]] = None


class DashboardCardsListDto(BaseModel):
    items: List[DashboardCardDto] = Field(default_factory=list)
    total: int = 0
