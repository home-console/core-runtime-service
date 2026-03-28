"""Capability registry for provider/consumer metadata."""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Dict, List, Optional, Tuple

from core.capability_protocol import PROTOCOL_VERSION, ProviderMetadata
from core.capability.security import (
    check_capability_namespace_permission,
    trust_level_to_privilege,
)


class CapabilityRegistry:
    def __init__(self) -> None:
        self._providers: Dict[str, List[Dict[str, Any]]] = {}
        self._consumers: Dict[str, List[str]] = {}
        self._sync_lock = threading.RLock()
        self._async_lock: Optional[asyncio.Lock] = None

    @property
    def _lock(self) -> asyncio.Lock:
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock

    async def register_provider(
        self,
        plugin_name: str,
        capability_id: str,
        provider_type: str = "local",
        remote_config: Optional[Dict[str, Any]] = None,
        execution_mode: str = "in_process",
        process_config: Optional[Dict[str, Any]] = None,
        container_config: Optional[Dict[str, Any]] = None,
        plugin_privilege: str = "user",
    ) -> None:
        check_capability_namespace_permission(
            capability_id, plugin_name, plugin_privilege
        )

        async with self._lock:
            if capability_id not in self._providers:
                self._providers[capability_id] = []

            existing = next(
                (
                    p
                    for p in self._providers[capability_id]
                    if p["plugin"] == plugin_name
                ),
                None,
            )
            if existing:
                return

            provider_info: Dict[str, Any] = {
                "plugin": plugin_name,
                "type": provider_type,
                "protocol_version": PROTOCOL_VERSION,
                "provider_version": None,
                "healthy": True,
                "timeouts": {},
                "capabilities": [],
                "execution_mode": execution_mode,
            }
            if remote_config:
                provider_info["remote_config"] = remote_config
            if process_config:
                provider_info["process_config"] = process_config
            if container_config:
                provider_info["container_config"] = container_config

            self._providers[capability_id].append(provider_info)

    async def update_provider_metadata(
        self,
        plugin_name: str,
        capability_id: str,
        protocol_version: Optional[int] = None,
        provider_version: Optional[str] = None,
        capabilities: Optional[List[str]] = None,
        timeouts: Optional[Dict[str, float]] = None,
        execution_mode: Optional[str] = None,
        process_config: Optional[Dict[str, Any]] = None,
        container_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        async with self._lock:
            provider = self._get_provider_entry(capability_id, plugin_name)
            if not provider:
                return

            if protocol_version is not None:
                provider["protocol_version"] = protocol_version
            if provider_version is not None:
                provider["provider_version"] = provider_version
            if capabilities is not None:
                provider["capabilities"] = capabilities
            if timeouts is not None:
                provider["timeouts"] = timeouts
            if execution_mode is not None:
                provider["execution_mode"] = execution_mode
            if process_config is not None:
                provider["process_config"] = process_config
            if container_config is not None:
                provider["container_config"] = container_config

    async def set_provider_health(
        self,
        plugin_name: str,
        capability_id: str,
        healthy: bool,
        version: Optional[str] = None,
    ) -> None:
        async with self._lock:
            provider = self._get_provider_entry(capability_id, plugin_name)
            if not provider:
                return

            provider["healthy"] = healthy
            if version:
                provider["provider_version"] = version

    async def register_consumer(self, plugin_name: str, capability_id: str) -> None:
        async with self._lock:
            if plugin_name not in self._consumers:
                self._consumers[plugin_name] = []
            if capability_id not in self._consumers[plugin_name]:
                self._consumers[plugin_name].append(capability_id)

    async def unregister_plugin(self, plugin_name: str) -> None:
        async with self._lock:
            for cap_id, providers in list(self._providers.items()):
                self._providers[cap_id] = [
                    p for p in providers if p["plugin"] != plugin_name
                ]
                if not self._providers[cap_id]:
                    del self._providers[cap_id]
            self._consumers.pop(plugin_name, None)

    def get_providers(self, capability_id: str) -> List[str]:
        with self._sync_lock:
            providers = self._providers.get(capability_id, [])
            healthy_local = [
                p for p in providers if p["healthy"] and p["type"] == "local"
            ]
            healthy_remote = [
                p for p in providers if p["healthy"] and p["type"] == "remote"
            ]
            unhealthy = [p for p in providers if not p["healthy"]]
            result = healthy_local + healthy_remote + unhealthy
            return [p["plugin"] for p in result]

    def get_providers_sorted_by_health(self, capability_id: str) -> List[str]:
        with self._sync_lock:
            providers = self._providers.get(capability_id, [])
            healthy = [p for p in providers if p["healthy"]]
            local = [p for p in healthy if p["type"] == "local"]
            remote = [p for p in healthy if p["type"] == "remote"]
            result = local + remote
            return [p["plugin"] for p in result]

    def _get_provider_entry(
        self,
        capability_id: str,
        plugin_name: str,
    ) -> Optional[Dict[str, Any]]:
        providers = self._providers.get(capability_id, [])
        return next((p for p in providers if p["plugin"] == plugin_name), None)

    def get_provider_info(
        self,
        capability_id: str,
        provider_name: str,
    ) -> Optional[Dict[str, Any]]:
        with self._sync_lock:
            provider = self._get_provider_entry(capability_id, provider_name)
            if provider:
                return dict(provider)
            return None

    def get_all_providers_for_capability(
        self, capability_id: str
    ) -> List[Dict[str, Any]]:
        with self._sync_lock:
            providers = self._providers.get(capability_id, [])
            return [dict(p) for p in providers]

    def get_required_capabilities(self, plugin_name: str) -> List[str]:
        with self._sync_lock:
            return list(self._consumers.get(plugin_name, []))

    def provider_info_to_metadata(
        self, provider_info: Dict[str, Any]
    ) -> ProviderMetadata:
        return ProviderMetadata(
            plugin_name=provider_info.get("plugin", ""),
            provider_type=provider_info.get("type", "local"),
            protocol_version=provider_info.get("protocol_version", 1),
            provider_version=provider_info.get("provider_version"),
            timeouts=provider_info.get("timeouts", {}),
            capabilities=provider_info.get("capabilities", []),
            remote_config=provider_info.get("remote_config"),
            execution_mode=provider_info.get("execution_mode", "in_process"),
            process_config=provider_info.get("process_config"),
            container_config=provider_info.get("container_config"),
        )

    def select_provider_for(self, capability_id: str) -> Optional[ProviderMetadata]:
        with self._sync_lock:
            providers = self._providers.get(capability_id, [])
            if not providers:
                return None

            healthy_local = [
                p
                for p in providers
                if p.get("healthy", True) and p.get("type") == "local"
            ]
            healthy_remote = [
                p
                for p in providers
                if p.get("healthy", True) and p.get("type") == "remote"
            ]

            selected_provider = None
            if healthy_local:
                selected_provider = healthy_local[0]
            elif healthy_remote:
                selected_provider = healthy_remote[0]
            else:
                selected_provider = providers[0]

            if not selected_provider:
                return None

            return self.provider_info_to_metadata(selected_provider)

    async def validate_plugin_requirements(
        self, plugin_name: str
    ) -> Tuple[bool, List[str]]:
        required = self.get_required_capabilities(plugin_name)
        missing: List[str] = []
        for cap_id in required:
            if not self.get_providers(cap_id):
                missing.append(cap_id)
        return (len(missing) == 0, missing)

    def trust_level_to_privilege(self, trust_level: object = None) -> str:
        return trust_level_to_privilege(trust_level)

