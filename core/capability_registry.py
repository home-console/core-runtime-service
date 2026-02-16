"""
CapabilityRegistry — метаданный реестр capability → provider и plugin → required capabilities.

Только декларации, проверки, интроспекция, диагностика.
НЕ знает о сервисах, ServiceRegistry, конкретных реализациях.
НЕ имеет методов call / resolve / invoke.

Поддерживает локальные и remote providers.
"""

from __future__ import annotations

from typing import Dict, List, Tuple, Optional, Any


class CapabilityRegistry:
    """
    Реестр метаданных: кто какой capability предоставляет и кто какой требует.

    Поддерживает:
    - Локальные providers (типовые плагины)
    - Remote providers (через HTTP)

    API:
    - register_provider(plugin_name, capability_id, provider_type="local", remote_config=None)
    - register_consumer(plugin_name, capability_id)
    - unregister_plugin(plugin_name)
    - get_providers(capability_id) -> List[str]
    - get_provider_info(plugin_name, capability_id) -> {"type": "local"|"remote", ...}
    - get_required_capabilities(plugin_name) -> List[str]
    - validate_plugin_requirements(plugin_name) -> (ok: bool, missing: List[str])
    """

    def __init__(self) -> None:
        # capability_id -> [{"name": plugin_name, "type": "local"|"remote", "config": {...}}, ...]
        self._providers: Dict[str, List[Dict[str, Any]]] = {}
        # plugin_name -> list of capability_ids that plugin requires
        self._consumers: Dict[str, List[str]] = {}

    def register_provider(
        self,
        plugin_name: str,
        capability_id: str,
        provider_type: str = "local",
        remote_config: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Зарегистрировать плагин как провайдер capability.
        
        Args:
            plugin_name: имя плагина
            capability_id: ID capability
            provider_type: "local" или "remote"
            remote_config: конфиг для remote provider (если type="remote")
        """
        if capability_id not in self._providers:
            self._providers[capability_id] = []
        
        # Проверяем, не зарегистрирован ли уже этот провайдер
        existing = next(
            (p for p in self._providers[capability_id] if p["name"] == plugin_name),
            None
        )
        if existing:
            return  # Уже есть
        
        provider_info: Dict[str, Any] = {
            "name": plugin_name,
            "type": provider_type,
        }
        if remote_config:
            provider_info["remote_config"] = remote_config
        
        self._providers[capability_id].append(provider_info)

    def register_consumer(self, plugin_name: str, capability_id: str) -> None:
        """Зарегистрировать плагин как потребитель capability."""
        if plugin_name not in self._consumers:
            self._consumers[plugin_name] = []
        if capability_id not in self._consumers[plugin_name]:
            self._consumers[plugin_name].append(capability_id)

    def unregister_plugin(self, plugin_name: str) -> None:
        """Удалить плагин из реестра (как провайдер и как потребитель)."""
        for cap_id, providers in list(self._providers.items()):
            # Удаляем провайдер по имени
            self._providers[cap_id] = [
                p for p in providers if p["name"] != plugin_name
            ]
            if not self._providers[cap_id]:
                del self._providers[cap_id]
        self._consumers.pop(plugin_name, None)

    def get_providers(self, capability_id: str) -> List[str]:
        """
        Список имён плагинов, предоставляющих capability.
        
        Приоритет: локальные providers первыми.
        """
        providers = self._providers.get(capability_id, [])
        
        # Сортируем: локальные первыми
        local_providers = [p["name"] for p in providers if p["type"] == "local"]
        remote_providers = [p["name"] for p in providers if p["type"] == "remote"]
        
        return local_providers + remote_providers

    def get_provider_info(
        self,
        capability_id: str,
        provider_name: str
    ) -> Optional[Dict[str, Any]]:
        """Получить информацию о конкретном провайдере capability."""
        providers = self._providers.get(capability_id, [])
        return next(
            (p for p in providers if p["name"] == provider_name),
            None
        )

    def get_all_providers_for_capability(
        self,
        capability_id: str
    ) -> List[Dict[str, Any]]:
        """Получить полную информацию всех провайдеров capability."""
        providers = self._providers.get(capability_id, [])
        # Копируем для безопасности
        return [dict(p) for p in providers]

    def get_required_capabilities(self, plugin_name: str) -> List[str]:
        """Получить список capability, требуемых плагином."""
        return self._consumers.get(plugin_name, [])

    def validate_plugin_requirements(self, plugin_name: str) -> Tuple[bool, List[str]]:
        """
        Проверить, что все требуемые плагину capabilities имеют хотя бы одного provider.

        Returns:
            (True, []) если все требования удовлетворены.
            (False, [missing_capability_id, ...]) если какие-то capabilities отсутствуют.
        """
        required = self.get_required_capabilities(plugin_name)
        missing: List[str] = []
        for cap_id in required:
            if not self.get_providers(cap_id):
                missing.append(cap_id)
        return (len(missing) == 0, missing)
