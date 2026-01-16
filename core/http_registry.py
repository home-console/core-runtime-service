"""
HTTP Interface Registry для Core Runtime.

Хранит декларативные HTTP-контракты плагинов.
Не выполняет HTTP-запросы и не зависит от фреймворков.
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class HttpEndpoint:
    """Описание HTTP-контракта.

    Поля:
      - method: HTTP-метод (GET, POST и т.д.)
      - path: путь, обязательно начинается с '/'
      - service: имя runtime-сервиса (строка)
      - description: необязательное описание
      - version: опциональная версия API (например, "v1", "v2")
      - deprecated: флаг устаревшей версии (True если версия помечена как deprecated)
    """
    method: str
    path: str
    service: str
    description: Optional[str] = None
    version: Optional[str] = None
    deprecated: bool = False


class HttpRegistry:
    """Реестр HTTP-контрактов.

    Методы: `register`, `list`, `clear`.
    """

    def __init__(self):
        # internal store: list of HttpEndpoint
        self._endpoints: List[HttpEndpoint] = []
        # set of (method, path) for quick uniqueness check
        self._index = set()

    def register(self, endpoint: HttpEndpoint, version: Optional[str] = None) -> None:
        """Зарегистрировать HTTP-контракт.

        Выполняет валидацию и предотвращает дубли по (method,path).
        Нормализует path: удаляет завершающий '/' (кроме корня '/'),
        чтобы устранить дублирование путей в Swagger.
        
        Args:
            endpoint: описание HTTP-контракта
            version: опциональная версия API (если не указана в endpoint.version)
        """
        if not isinstance(endpoint.method, str) or not endpoint.method:
            raise ValueError("method должен быть непустой строкой")
        method = endpoint.method.upper()

        if not isinstance(endpoint.path, str) or not endpoint.path.startswith("/"):
            raise ValueError("path должен быть строкой, начинающейся с '/'")

        if not isinstance(endpoint.service, str) or not endpoint.service.strip():
            raise ValueError("service должен быть непустой строкой")

        # Используем версию из endpoint или из параметра
        api_version = endpoint.version or version
        
        # Нормализуем путь: убираем завершающий '/', если это не корень '/'
        # Причина: устранение дублирования /path и /path/ в Swagger.
        # Делается здесь (в HttpRegistry), чтобы не изменять плагины.
        path = endpoint.path.rstrip("/") if endpoint.path != "/" else endpoint.path
        
        # Если указана версия, добавляем её к пути
        if api_version:
            # Убираем ведущий слэш из версии если есть
            version_prefix = api_version.lstrip("/")
            # Добавляем версию к пути: /v1/path или /v2/path
            path = f"/{version_prefix}{path}"

        key = (method, path)
        if key in self._index:
            raise ValueError(f"Контракт для {method} {path} уже зарегистрирован")

        # Нормализуем метод и добавляем запись
        ep = HttpEndpoint(
            method=method,
            path=path,
            service=endpoint.service,
            description=endpoint.description,
            version=api_version
        )
        self._endpoints.append(ep)
        self._index.add(key)

    def list(self) -> List[HttpEndpoint]:
        """Вернуть копию списка всех зарегистрированных контрактов."""
        return list(self._endpoints)

    def clear(self, plugin_name: Optional[str] = None) -> None:
        """Удалить контракты.

        Если `plugin_name` None — удалить все.
        Иначе удалить контракты, владельцем которых является плагин, 
        выводимый из prefix-а имени сервиса (до первой точки).
        """
        if plugin_name is None:
            self._endpoints.clear()
            self._index.clear()
            return

        def owner_of(service: str) -> Optional[str]:
            if not service:
                return None
            return service.split(".")[0]

        remaining = []
        new_index = set()
        for ep in self._endpoints:
            owner = owner_of(ep.service)
            if owner == plugin_name:
                continue
            remaining.append(ep)
            new_index.add((ep.method, ep.path))

        self._endpoints = remaining
        self._index = new_index
    
    def get_versions(self, service_name: str) -> List[str]:
        """
        Получить список всех версий для сервиса.
        
        Args:
            service_name: имя сервиса (например, "devices.list")
        
        Returns:
            Список версий (например, ["v1", "v2"])
        
        Пример:
            versions = http_registry.get_versions("devices.list")
            # Вернёт ["v1", "v2"] если есть /v1/devices/list и /v2/devices/list
        """
        versions = set()
        for endpoint in self._endpoints:
            if endpoint.service == service_name and endpoint.version:
                versions.add(endpoint.version)
        return sorted(list(versions))
    
    def is_deprecated(self, service_name: str, version: Optional[str] = None) -> bool:
        """
        Проверить, является ли версия сервиса устаревшей.
        
        Args:
            service_name: имя сервиса
            version: версия API (если None, проверяет все версии)
        
        Returns:
            True если версия помечена как deprecated
        
        Пример:
            if http_registry.is_deprecated("devices.list", "v1"):
                print("Версия v1 устарела, используйте v2")
        """
        for endpoint in self._endpoints:
            if endpoint.service == service_name:
                if version is None:
                    if endpoint.deprecated:
                        return True
                elif endpoint.version == version:
                    return endpoint.deprecated
        return False
    
    def mark_deprecated(self, service_name: str, version: str) -> None:
        """
        Пометить версию сервиса как устаревшую.
        
        Args:
            service_name: имя сервиса
            version: версия API для пометки как deprecated
        
        Raises:
            ValueError: если сервис или версия не найдены
        
        Пример:
            http_registry.mark_deprecated("devices.list", "v1")
        """
        found = False
        for endpoint in self._endpoints:
            if endpoint.service == service_name and endpoint.version == version:
                endpoint.deprecated = True
                found = True
        if not found:
            raise ValueError(f"Сервис '{service_name}' версии '{version}' не найден")
    
    def generate_openapi(
        self,
        title: str = "Core Runtime API",
        version: str = "1.0.0",
        description: Optional[str] = None,
        servers: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Сгенерировать OpenAPI схему на основе зарегистрированных endpoints.
        
        Args:
            title: заголовок API
            version: версия API документации
            description: описание API
            servers: список серверов (например, [{"url": "http://localhost:8000"}])
        
        Returns:
            Словарь с OpenAPI схемой в формате OpenAPI 3.0.0
        
        Пример:
            schema = http_registry.generate_openapi(
                title="Home Console API",
                version="1.0.0",
                description="API для управления умным домом"
            )
        """
        paths: Dict[str, Dict[str, Any]] = {}
        
        for endpoint in self._endpoints:
            path = endpoint.path
            method = endpoint.method.lower()
            
            # Инициализируем путь, если его ещё нет
            if path not in paths:
                paths[path] = {}
            
            # Создаём операцию для метода
            operation: Dict[str, Any] = {
                "summary": endpoint.description or f"{method.upper()} {path}",
                "operationId": endpoint.service.replace(".", "_").replace("-", "_"),
                "responses": {
                    "200": {
                        "description": "Success",
                        "content": {
                            "application/json": {
                                "schema": {"type": "object"}
                            }
                        }
                    },
                    "400": {
                        "description": "Bad Request",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "detail": {"type": "string"}
                                    }
                                }
                            }
                        }
                    },
                    "500": {
                        "description": "Internal Server Error",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "detail": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
            
            # Добавляем tags на основе версии или пути
            tags = []
            if endpoint.version:
                tags.append(f"v{endpoint.version.lstrip('v')}")
            # Извлекаем первый сегмент пути как tag (например, "/api/devices" -> "api")
            path_parts = [p for p in path.split("/") if p]
            if path_parts:
                # Пропускаем версию если она есть
                if path_parts[0].startswith("v") and path_parts[0][1:].isdigit():
                    if len(path_parts) > 1:
                        tags.append(path_parts[1])
                else:
                    tags.append(path_parts[0])
            
            if tags:
                operation["tags"] = tags
            
            # Для POST/PUT/PATCH добавляем requestBody
            if method in ("post", "put", "patch"):
                operation["requestBody"] = {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"type": "object"}
                        }
                    }
                }
            
            # Добавляем deprecation warning если версия устарела
            if endpoint.deprecated:
                operation["deprecated"] = True
                # Добавляем предупреждение в описание
                if operation.get("summary"):
                    operation["summary"] = f"[DEPRECATED] {operation['summary']}"
            
            paths[path][method] = operation
        
        # Строим OpenAPI схему
        openapi_schema: Dict[str, Any] = {
            "openapi": "3.0.0",
            "info": {
                "title": title,
                "version": version
            },
            "paths": paths
        }
        
        if description:
            openapi_schema["info"]["description"] = description
        
        if servers:
            openapi_schema["servers"] = servers
        
        return openapi_schema