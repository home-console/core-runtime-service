from __future__ import annotations

from typing import Optional

from core.service.models import ServiceFunc


class ServiceRouter:
    """Routing logic for service lookup, versions and deprecation metadata."""

    def __init__(self, services: dict[str, ServiceFunc]) -> None:
        self._services = services
        self._deprecated: dict[str, bool] = {}

    def register(self, service_name: str) -> None:
        self._deprecated[service_name] = False

    def unregister(self, service_name: str) -> None:
        self._deprecated.pop(service_name, None)

    def clear(self) -> None:
        self._deprecated.clear()

    def resolve(self, service_name: str) -> Optional[ServiceFunc]:
        return self._services.get(service_name)

    def get_versions(self, service_name: str) -> list[str]:
        versions: list[str] = []
        for registered_name in self._services.keys():
            if registered_name == service_name:
                versions.append("")
            elif registered_name.startswith(f"{service_name}."):
                version = registered_name[len(service_name) + 1 :]
                if version not in versions:
                    versions.append(version)
        return sorted(versions)

    def is_deprecated(self, service_name: str, version: Optional[str] = None) -> bool:
        versioned_name = f"{service_name}.{version}" if version else service_name
        return self._deprecated.get(versioned_name, False)

    def mark_deprecated(self, service_name: str, version: Optional[str] = None) -> None:
        versioned_name = f"{service_name}.{version}" if version else service_name
        if versioned_name not in self._services:
            raise ValueError(f"Сервис '{versioned_name}' не найден")
        self._deprecated[versioned_name] = True

