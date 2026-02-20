"""
CapabilityRegistry — метаданный реестр capability → provider и plugin → required capabilities.

Поддерживает Capability Protocol v1:
- Tracking protocol_version per provider
- provider_version from manifest
- Health status and monitoring
- Per-capability timeouts
- Provider metadata

Только декларации, проверки, интроспекция, диагностика.
НЕ знает о сервисах, ServiceRegistry, конкретных реализациях.
НЕ имеет методов call / resolve / invoke.

Поддерживает локальные и remote providers.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Dict, List, Tuple, Optional, Any
from core.capability_protocol import (
    PROTOCOL_VERSION,
    ProviderMetadata,
    ProviderHealthStatus,
)
try:
    from core.trust.trust_store import TrustLevel
    HAS_TRUST_LAYER = True
except ImportError:
    HAS_TRUST_LAYER = False


class CapabilitySecurityError(Exception):
    """Capability security violation."""
    pass


# Namespace protection rules
# Step 11: Trust level mapping for capability registration
# - CORE (3) → can register system.*, admin.*, runtime.*
# - PUBLISHER (2) → can register admin.* but not system.*, runtime.*
# - DEVELOPER (1) → cannot register system.*, admin.*, runtime.*
# 
# Mapping to privilege levels:
# - trust_level_to_privilege: TrustLevel → plugin_privilege
TRUST_LEVEL_TO_PRIVILEGE = {
    "core": "core",        # TrustLevel.CORE (3) 
    "publisher": "admin",  # TrustLevel.PUBLISHER (2)
    "developer": "user",   # TrustLevel.DEVELOPER (1)
} if HAS_TRUST_LAYER else {}

PROTECTED_NAMESPACES = {
    "system.": "core",    # Only CORE trust level (core privilege)
    "admin.": "admin",    # Only PUBLISHER+ trust level (admin privilege)
    "runtime.": "core",   # Only CORE trust level (core privilege)
}


def _check_capability_namespace_permission(
    capability_id: str,
    plugin_name: str,
    plugin_privilege: str = "user"
) -> None:
    """
    Check if plugin has permission to register this capability.
    
    Step 11: Trust level enforcement for protected capabilities
    - system.* capabilities: ONLY CORE trusted keys (privilege=core)
    - admin.* capabilities: PUBLISHER and CORE keys (privilege=admin or core)
    - runtime.* capabilities: ONLY CORE trusted keys (privilege=core)
    - Custom capabilities: Any trusted plugin (privilege=admin, core, or user)
    
    Args:
        capability_id: Capability ID (e.g., "system.reboot")
        plugin_name: Plugin trying to register it
        plugin_privilege: Plugin privilege level ("core", "admin", "user")
            Maps from TrustLevel:
            - "core" ← TrustLevel.CORE
            - "admin" ← TrustLevel.PUBLISHER
            - "user" ← TrustLevel.DEVELOPER or unsigned
        
    Raises:
        CapabilitySecurityError: If plugin lacks permission
    """
    # Check protected namespaces
    for namespace_prefix, allowed_privilege in PROTECTED_NAMESPACES.items():
        if capability_id.startswith(namespace_prefix):
            # Step 11: Enhanced checking with trust level clarity
            if namespace_prefix == "system.":
                # system.* → only CORE level (privilege="core")
                if plugin_privilege != "core":
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register system.* capability '{capability_id}': "
                        f"requires CORE trust level (current privilege={plugin_privilege})"
                    )
            elif namespace_prefix == "admin.":
                # admin.* → PUBLISHER+ level (privilege="admin" or "core")
                if plugin_privilege not in ("core", "admin"):
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register admin.* capability '{capability_id}': "
                        f"requires PUBLISHER+ trust level (current privilege={plugin_privilege})"
                    )
            elif namespace_prefix == "runtime.":
                # runtime.* → only CORE level (privilege="core")
                if plugin_privilege != "core":
                    raise CapabilitySecurityError(
                        f"Plugin '{plugin_name}' cannot register runtime.* capability '{capability_id}': "
                        f"requires CORE trust level (current privilege={plugin_privilege})"
                    )
            break


class CapabilityRegistry:
    """
    Реестр метаданных: кто какой capability предоставляет и кто какой требует.

    Поддерживает Capability Protocol v1:
    - Локальные providers (типовые плагины)
    - Remote providers (через HTTP) с protocol versioning
    - Health monitoring
    - Per-capability timeouts

    API:
    - register_provider(plugin_name, capability_id, provider_type="local", remote_config=None)
    - register_consumer(plugin_name, capability_id)
    - unregister_plugin(plugin_name)
    - update_provider_metadata(plugin_name, capability_id, protocol_version, provider_version, ...)
    - set_provider_health(plugin_name, healthy, ...)
    - get_providers(capability_id) -> List[str]
    - get_provider_info(plugin_name, capability_id) -> ProviderMetadata
    - get_required_capabilities(plugin_name) -> List[str]
    - validate_plugin_requirements(plugin_name) -> (ok: bool, missing: List[str])
    """

    def __init__(self) -> None:
        # capability_id -> [ProviderMetadata, ...]
        # Stored as dicts for serialization compatibility
        self._providers: Dict[str, List[Dict[str, Any]]] = {}
        
        # plugin_name -> list of capability_ids that plugin requires
        self._consumers: Dict[str, List[str]] = {}
        
        # Use threading.Lock for sync getter methods that need lock protection
        # Async methods can also use threading.Lock safely in asyncio
        self._lock = threading.Lock()

    @staticmethod
    def trust_level_to_privilege(trust_level: Optional[Any]) -> str:
        """
        Step 11: Convert TrustLevel enum to privilege level for capability registration.
        
        Mapping:
        - TrustLevel.CORE ("core") → "core"
        - TrustLevel.PUBLISHER ("publisher") → "admin"
        - TrustLevel.DEVELOPER ("developer") → "user"
        - None (unsigned plugin) → "user"
        
        Args:
            trust_level: TrustLevel enum value or None
            
        Returns:
            privilege level string ("core", "admin", or "user")
        """
        if not HAS_TRUST_LAYER or trust_level is None:
            return "user"  # Default for unsigned plugins
        
        # TrustLevel enum has values: "core", "publisher", "developer"
        # Or it could be passed as enum member
        if hasattr(trust_level, 'value'):
            level_str = trust_level.value
        else:
            level_str = str(trust_level).lower()
        
        if level_str == "core":
            return "core"
        elif level_str == "publisher":
            return "admin"
        else:  # "developer" or anything else
            return "user"

    async def register_provider(
        self,
        plugin_name: str,
        capability_id: str,
        provider_type: str = "local",
        remote_config: Optional[Dict[str, Any]] = None,
        execution_mode: str = "in_process",
        process_config: Optional[Dict[str, Any]] = None,
        container_config: Optional[Dict[str, Any]] = None,
        plugin_privilege: str = "user"  # Security: Check namespace protection
    ) -> None:
        """
        Зарегистрировать плагин как провайдер capability.
        
        Step 11: Trust-aware capability registration
        - Verifies plugin has permission based on trust level (via plugin_privilege)
        - Prevents system.* registration by non-CORE plugins
        - Prevents admin.* registration by DEVELOPER-level plugins
        - Enforces capability security rules from trust store
        
        Args:
            plugin_name: имя плагина
            capability_id: ID capability (e.g., "system.reboot", "custom.weather")
            provider_type: "local" или "remote"
            remote_config: конфиг для remote provider (если type="remote")
            execution_mode: in_process | process | container | remote
            process_config: конфиг для process execution (если execution_mode="process")
            container_config: конфиг для container execution (если execution_mode="container")
            plugin_privilege: Plugin privilege level for namespace protection.
                Can be set via trust_level_to_privilege(trust_level):
                - "core" → TrustLevel.CORE (can register system.*, runtime.*, admin.*)
                - "admin" → TrustLevel.PUBLISHER (can register admin.* but not system.*)
                - "user" → TrustLevel.DEVELOPER or unsigned (can only register custom.* or public capabilities)
            
        Raises:
            CapabilitySecurityError: If plugin lacks permission to register this capability
                based on trust level and capability namespace rules
        """
        # Step 11: Trust-based security check
        # This enforces the capability security rules from the trust layer
        _check_capability_namespace_permission(capability_id, plugin_name, plugin_privilege)
        
        with self._lock:
            if capability_id not in self._providers:
                self._providers[capability_id] = []
            
            # Проверяем, не зарегистрирован ли уже этот провайдер
            existing = next(
                (p for p in self._providers[capability_id] if p["plugin"] == plugin_name),
                None
            )
            if existing:
                return  # Уже есть
            
            # Protocol v1: используем новую структуру с метаданными
            provider_info: Dict[str, Any] = {
                "plugin": plugin_name,
                "type": provider_type,
                "protocol_version": PROTOCOL_VERSION,
                "provider_version": None,  # Заполняется при manifest discovery
                "healthy": True,  # По умолчанию здоров
                "timeouts": {},  # Заполняется из manifest
                "capabilities": [],  # Заполняется из manifest
                "execution_mode": execution_mode,  # Plugin Isolation
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
        execution_mode: Optional[str] = None,  # Plugin Isolation
        process_config: Optional[Dict[str, Any]] = None,
        container_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Обновить метаданные провайдера после manifest discovery или health check.
        
        Args:
            execution_mode: in_process | process | container | remote 
            process_config: конфиг для process execution 
            container_config: конфиг для container execution 
        """
        with self._lock:
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
            if execution_mode is not None:  # Step 9
                provider["execution_mode"] = execution_mode
            if process_config is not None:  # Step 9
                provider["process_config"] = process_config
            if container_config is not None:  # Step 9
                provider["container_config"] = container_config

    async def set_provider_health(
        self,
        plugin_name: str,
        capability_id: str,
        healthy: bool,
        version: Optional[str] = None,
    ) -> None:
        """
        Обновить health status провайдера.
        """
        with self._lock:
            provider = self._get_provider_entry(capability_id, plugin_name)
            if not provider:
                return
            
            provider["healthy"] = healthy
            if version:
                provider["provider_version"] = version

    async def register_consumer(self, plugin_name: str, capability_id: str) -> None:
        """Зарегистрировать плагин как потребитель capability."""
        with self._lock:
            if plugin_name not in self._consumers:
                self._consumers[plugin_name] = []
            if capability_id not in self._consumers[plugin_name]:
                self._consumers[plugin_name].append(capability_id)

    async def unregister_plugin(self, plugin_name: str) -> None:
        """Удалить плагин из реестра (как провайдер и как потребитель)."""
        with self._lock:
            for cap_id, providers in list(self._providers.items()):
                # Удаляем провайдер по имени
                self._providers[cap_id] = [
                    p for p in providers if p["plugin"] != plugin_name
                ]
                if not self._providers[cap_id]:
                    del self._providers[cap_id]
            self._consumers.pop(plugin_name, None)

    def get_providers(self, capability_id: str) -> List[str]:
        """
        Список имён плагинов, предоставляющих capability.
        
        Приоритет: здоровые провайдеры первыми, локальные перед remote.
        """
        with self._lock:
            providers = self._providers.get(capability_id, [])
            
            # Сортируем: здоровые первыми, затем локальные перед remote
            healthy_local = [p for p in providers if p["healthy"] and p["type"] == "local"]
            healthy_remote = [p for p in providers if p["healthy"] and p["type"] == "remote"]
            unhealthy = [p for p in providers if not p["healthy"]]
            
            result = healthy_local + healthy_remote + unhealthy
            return [p["plugin"] for p in result]

    def get_providers_sorted_by_health(self, capability_id: str) -> List[str]:
        """
        Список провайдеров, отсортированные по здоровью (только здоровые).
        Используется при выборе провайдера для операции.
        """
        with self._lock:
            providers = self._providers.get(capability_id, [])
            
            # Только здоровые: локальные перед remote
            healthy = [p for p in providers if p["healthy"]]
            local = [p for p in healthy if p["type"] == "local"]
            remote = [p for p in healthy if p["type"] == "remote"]
            
            result = local + remote
            return [p["plugin"] for p in result]

    def _get_provider_entry(
        self,
        capability_id: str,
        plugin_name: str
    ) -> Optional[Dict[str, Any]]:
        """Получить entry провайдера для редактирования."""
        providers = self._providers.get(capability_id, [])
        return next(
            (p for p in providers if p["plugin"] == plugin_name),
            None
        )

    def get_provider_info(
        self,
        capability_id: str,
        provider_name: str
    ) -> Optional[Dict[str, Any]]:
        """Получить информацию о конкретном провайдере capability."""
        with self._lock:
            provider = self._get_provider_entry(capability_id, provider_name)
            if provider:
                return dict(provider)  # Copy для безопасности
            return None

    def get_all_providers_for_capability(
        self,
        capability_id: str
    ) -> List[Dict[str, Any]]:
        """Получить полную информацию всех провайдеров capability."""
        with self._lock:
            providers = self._providers.get(capability_id, [])
            return [dict(p) for p in providers]  # Копируем для безопасности

    def get_required_capabilities(self, plugin_name: str) -> List[str]:
        """Получить список capability, требуемых плагином."""
        with self._lock:
            return list(self._consumers.get(plugin_name, []))

    def provider_info_to_metadata(self, provider_info: Dict[str, Any]) -> ProviderMetadata:
        """
        Конвертировать provider_info dict в ProviderMetadata dataclass.
        
        Используется ExecutionRouter для получения metadata для routing операций.
        Plugin Isolation — получаем execution_mode и configs отсюда.
        """
        return ProviderMetadata(
            plugin_name=provider_info.get("plugin", ""),
            provider_type=provider_info.get("type", "local"),
            protocol_version=provider_info.get("protocol_version", 1),
            provider_version=provider_info.get("provider_version"),
            timeouts=provider_info.get("timeouts", {}),
            capabilities=provider_info.get("capabilities", []),
            remote_config=provider_info.get("remote_config"),
            execution_mode=provider_info.get("execution_mode", "in_process"),  # Step 9
            process_config=provider_info.get("process_config"),  # Step 9
            container_config=provider_info.get("container_config"),  # Step 9
        )

    def select_provider_for(self, capability_id: str) -> Optional[ProviderMetadata]:
        """
        Выбрать провайдера для capability с инкапсулированной логикой выбора.
        
        Этот метод инкапсулирует выбор провайдера, включая:
        - Блокировку для атомарного выбора
        - Применение политики выбора (здоровые провайдеры, локальные перед remote)
        - Конвертацию в ProviderMetadata
        
        Args:
            capability_id: ID capability для которой нужен провайдер
            
        Returns:
            ProviderMetadata выбранного провайдера или None, если провайдеров нет
            
        Note:
            Выбор провайдера атомарный (под локом), но возвращаемый объект
            является snapshot'ом состояния на момент выбора. Провайдер может
            измениться или исчезнуть после возврата из метода.
        """
        with self._lock:
            providers = self._providers.get(capability_id, [])
            if not providers:
                return None
            
            # Применяем политику выбора: здоровые провайдеры, локальные перед remote
            healthy_local = [p for p in providers if p.get("healthy", True) and p.get("type") == "local"]
            healthy_remote = [p for p in providers if p.get("healthy", True) and p.get("type") == "remote"]
            
            # Выбираем первого подходящего (можно расширить до weighted/round-robin)
            selected_provider = None
            if healthy_local:
                selected_provider = healthy_local[0]
            elif healthy_remote:
                selected_provider = healthy_remote[0]
            else:
                # Если нет здоровых, берём первого (fallback)
                selected_provider = providers[0]
            
            if not selected_provider:
                return None
            
            # Конвертируем в ProviderMetadata
            return self.provider_info_to_metadata(selected_provider)

    async def validate_plugin_requirements(self, plugin_name: str) -> Tuple[bool, List[str]]:
        """
        Проверить, что все требуемые плагину capabilities имеют хотя бы одного provider.

        Returns:
            (True, []) если все требования удовлетворены.
            (False, [missing_capability_id, ...]) если какие-то capabilities отсутствуют.
        """
        # Не держим self._lock здесь: get_required_capabilities и get_providers сами его берут.
        # Иначе один поток держит lock и вызывает getters, которые снова берут тот же Lock → дедлок.
        required = self.get_required_capabilities(plugin_name)
        missing: List[str] = []
        for cap_id in required:
            if not self.get_providers(cap_id):
                missing.append(cap_id)
        return (len(missing) == 0, missing)

