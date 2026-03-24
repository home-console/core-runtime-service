"""HTTP registry and endpoint models for modules layer."""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional


@dataclass
class EndpointAuthConfig:
    public: bool = False
    required_scopes: Optional[List[str]] = None
    requires_resource_check: bool = False
    resource_adapter: Optional[str] = None


@dataclass
class EndpointParamMapping:
    param_extractor: Optional[
        Callable[
            [Any, Optional[Dict[str, Any]], Dict[str, Any], Dict[str, Any]],
            Awaitable[Dict[str, Any]],
        ]
    ] = None
    body_validator: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None


@dataclass
class HttpEndpoint:
    path: str
    service: str
    method: Optional[str] = None
    websocket: bool = False
    description: Optional[str] = None
    version: Optional[str] = None
    deprecated: bool = False
    kind: Literal["api", "webhook"] = "api"
    tags: Optional[list[str]] = None
    auth_config: Optional[EndpointAuthConfig] = None
    param_mapping: Optional[EndpointParamMapping] = None

    def __post_init__(self) -> None:
        if self.websocket:
            if self.method is not None:
                raise ValueError("Если websocket=True → method должен быть None")
        else:
            if not self.method:
                raise ValueError(
                    "Если websocket=False → method обязателен (непустая строка)"
                )

        if self.tags is None:
            self.tags = []


class HttpRegistry:
    def __init__(self):
        self._endpoints: List[HttpEndpoint] = []
        self._index: set[tuple[str, str]] = set()

    def register(self, endpoint: HttpEndpoint, version: Optional[str] = None) -> None:
        if not endpoint.path.startswith("/"):
            raise ValueError("path должен быть строкой, начинающейся с '/'")

        if not endpoint.service.strip():
            raise ValueError("service должен быть непустой строкой")

        if not endpoint.websocket:
            if not isinstance(endpoint.method, str) or not endpoint.method:
                raise ValueError(
                    "method должен быть непустой строкой для HTTP endpoints"
                )

        api_version = endpoint.version or version
        path = endpoint.path.rstrip("/") if endpoint.path != "/" else endpoint.path

        if api_version:
            version_prefix = api_version.lstrip("/")
            path = f"/{version_prefix}{path}"

        if endpoint.websocket:
            key = ("WS", path)
        else:
            method_str = endpoint.method
            assert method_str is not None, "HTTP endpoint должен иметь method"
            key = (method_str.upper(), path)

        if key in self._index:
            key_str = f"WebSocket {path}" if endpoint.websocket else f"{key[0]} {path}"
            raise ValueError(f"Контракт для {key_str} уже зарегистрирован")

        ep = HttpEndpoint(
            path=path,
            service=endpoint.service,
            method=endpoint.method.upper() if endpoint.method else None,
            websocket=endpoint.websocket,
            description=endpoint.description,
            version=api_version,
            kind=endpoint.kind,
            tags=endpoint.tags or [],
            auth_config=endpoint.auth_config,
            param_mapping=endpoint.param_mapping,
        )
        self._endpoints.append(ep)
        self._index.add(key)

    def list(self) -> List[HttpEndpoint]:
        return list(self._endpoints)

    def clear(self, plugin_name: Optional[str] = None) -> None:
        if plugin_name is None:
            self._endpoints.clear()
            self._index.clear()
            return

        def owner_of(service: str) -> Optional[str]:
            if not service:
                return None
            return service.split(".")[0]

        remaining: List[HttpEndpoint] = []
        new_index: set[tuple[str, str]] = set()
        for ep in self._endpoints:
            owner = owner_of(ep.service)
            if owner == plugin_name:
                continue
            remaining.append(ep)
            method_key = ep.method if ep.method is not None else "WS"
            new_index.add((method_key, ep.path))

        self._endpoints = remaining
        self._index = new_index

    def get_versions(self, service_name: str) -> List[str]:
        versions: set[str] = set()
        for endpoint in self._endpoints:
            if endpoint.service == service_name and endpoint.version:
                versions.add(endpoint.version)
        return sorted(list(versions))

    def is_deprecated(self, service_name: str, version: Optional[str] = None) -> bool:
        for endpoint in self._endpoints:
            if endpoint.service == service_name:
                if version is None:
                    if endpoint.deprecated:
                        return True
                elif endpoint.version == version:
                    return endpoint.deprecated
        return False

    def mark_deprecated(self, service_name: str, version: str) -> None:
        found = False
        for endpoint in self._endpoints:
            if endpoint.service == service_name and endpoint.version == version:
                endpoint.deprecated = True
                found = True
        if not found:
            raise ValueError(f"Сервис '{service_name}' версии '{version}' не найден")
