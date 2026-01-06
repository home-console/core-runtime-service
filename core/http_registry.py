"""
HTTP Interface Registry для Core Runtime.

Хранит декларативные HTTP-контракты плагинов.
Не выполняет HTTP-запросы и не зависит от фреймворков.
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class HttpEndpoint:
    """Описание HTTP-контракта.

    Поля:
      - method: HTTP-метод (GET, POST и т.д.)
      - path: путь, обязательно начинается с '/'
      - service: имя runtime-сервиса (строка)
      - description: необязательное описание
    """
    method: str
    path: str
    service: str
    description: Optional[str] = None


class HttpRegistry:
    """Реестр HTTP-контрактов.

    Методы: `register`, `list`, `clear`.
    """

    def __init__(self):
        # internal store: list of HttpEndpoint
        self._endpoints: List[HttpEndpoint] = []
        # set of (method, path) for quick uniqueness check
        self._index = set()

    def register(self, endpoint: HttpEndpoint) -> None:
        """Зарегистрировать HTTP-контракт.

        Выполняет валидацию и предотвращает дубли по (method,path).
        """
        if not isinstance(endpoint.method, str) or not endpoint.method:
            raise ValueError("method должен быть непустой строкой")
        method = endpoint.method.upper()

        if not isinstance(endpoint.path, str) or not endpoint.path.startswith("/"):
            raise ValueError("path должен быть строкой, начинающейся с '/'")

        if not isinstance(endpoint.service, str) or not endpoint.service.strip():
            raise ValueError("service должен быть непустой строкой")

        key = (method, endpoint.path)
        if key in self._index:
            raise ValueError(f"Контракт для {method} {endpoint.path} уже зарегистрирован")

        # Нормализуем метод и добавляем запись
        ep = HttpEndpoint(method=method, path=endpoint.path, service=endpoint.service, description=endpoint.description)
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
