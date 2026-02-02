"""
CapabilityRegistry — метаданный реестр capability → provider и plugin → required capabilities.

Только декларации, проверки, интроспекция, диагностика.
НЕ знает о сервисах, ServiceRegistry, конкретных реализациях.
НЕ имеет методов call / resolve / invoke.
"""

from __future__ import annotations

from typing import Dict, List, Tuple


class CapabilityRegistry:
    """
    Реестр метаданных: кто какой capability предоставляет и кто какой требует.

    API:
    - register_provider(plugin_name, capability_id)
    - register_consumer(plugin_name, capability_id)
    - unregister_plugin(plugin_name)
    - get_providers(capability_id) -> List[str]
    - get_required_capabilities(plugin_name) -> List[str]
    - validate_plugin_requirements(plugin_name) -> (ok: bool, missing: List[str])
    """

    def __init__(self) -> None:
        # capability_id -> list of plugin names that provide it
        self._providers: Dict[str, List[str]] = {}
        # plugin_name -> list of capability_ids that plugin requires
        self._consumers: Dict[str, List[str]] = {}

    def register_provider(self, plugin_name: str, capability_id: str) -> None:
        """Зарегистрировать плагин как провайдер capability."""
        if capability_id not in self._providers:
            self._providers[capability_id] = []
        if plugin_name not in self._providers[capability_id]:
            self._providers[capability_id].append(plugin_name)

    def register_consumer(self, plugin_name: str, capability_id: str) -> None:
        """Зарегистрировать плагин как потребитель capability."""
        if plugin_name not in self._consumers:
            self._consumers[plugin_name] = []
        if capability_id not in self._consumers[plugin_name]:
            self._consumers[plugin_name].append(capability_id)

    def unregister_plugin(self, plugin_name: str) -> None:
        """Удалить плагин из реестра (как провайдер и как потребитель)."""
        for cap_id, providers in list(self._providers.items()):
            if plugin_name in providers:
                providers.remove(plugin_name)
            if not providers:
                del self._providers[cap_id]
        self._consumers.pop(plugin_name, None)

    def get_providers(self, capability_id: str) -> List[str]:
        """Список имён плагинов, предоставляющих capability."""
        return list(self._providers.get(capability_id, []))

    def get_required_capabilities(self, plugin_name: str) -> List[str]:
        """Список capability_id, которые требуются плагину."""
        return list(self._consumers.get(plugin_name, []))

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
