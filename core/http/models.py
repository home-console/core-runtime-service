"""
HTTP Endpoint Models .

Декларативные модели для HTTP-контрактов:
- EndpointAuthConfig: конфигурация авторизации
- EndpointParamMapping: маппинг параметров
- HttpEndpoint: описание HTTP-контракта
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Literal, Optional


@dataclass
class EndpointAuthConfig:
    """
    Декларативная конфигурация авторизации для endpoint.

    Декларативная authz и param_mapping для endpoints.
    """

    # Публичный endpoint (не требует авторизации)
    public: bool = False

    # Требуемые scopes (если не публичный)
    required_scopes: Optional[List[str]] = None

    # Проверка ресурса (resource-based authorization)
    # Если True, endpoint будет получать resource из доменного адаптера
    requires_resource_check: bool = False

    # Имя доменного адаптера для получения resource (например, "devices", "auth")
    # Если указано, route_binding будет вызывать соответствующий адаптер
    resource_adapter: Optional[str] = None


@dataclass
class EndpointParamMapping:
    """
    Декларативная конфигурация маппинга параметров для endpoint.

    Декларативная конфигурация маппинга параметров.
    """

    # Функция для извлечения/преобразования параметров из request
    # Принимает: (request, body, path_params, query_params) -> dict для service call
    param_extractor: Optional[
        Callable[[Any, Optional[Dict], Dict, Dict], Awaitable[Dict]]
    ] = None

    # Функция для валидации body перед вызовом сервиса
    body_validator: Optional[Callable[[Dict], Dict]] = None


@dataclass
class HttpEndpoint:
    """Описание HTTP-контракта.

    Поля:
      - path: путь, обязательно начинается с '/'
      - service: имя runtime-сервиса (строка)
      - method: HTTP-метод (GET, POST и т.д.) — обязателен если websocket=False
      - websocket: флаг WebSocket endpoint — если True, method должен быть None
      - description: необязательное описание
      - version: опциональная версия API (например, "v1", "v2")
      - deprecated: флаг устаревшей версии (True если версия помечена как deprecated)
      - kind: тип endpoint ("api" или "webhook") — определяет обработку и авторизацию
      - tags: опциональный список тегов для группировки в документации
      - auth_config: декларативная конфигурация авторизации
      - param_mapping: декларативная конфигурация маппинга параметров

    Правила валидации:
      - Если websocket=True → method должен быть None
      - Если websocket=False → method обязателен (не пустая строка)
    """

    path: str
    service: str
    method: Optional[str] = None
    websocket: bool = False
    description: Optional[str] = None
    version: Optional[str] = None
    deprecated: bool = False
    kind: Literal["api", "webhook"] = "api"
    tags: Optional[list[str]] = None
    # Декларативная authz и param_mapping
    auth_config: Optional[EndpointAuthConfig] = None
    param_mapping: Optional[EndpointParamMapping] = None

    def __post_init__(self) -> None:
        """Валидация endpoint после инициализации."""
        # Валидация websocket vs method
        if self.websocket:
            if self.method is not None:
                raise ValueError("Если websocket=True → method должен быть None")
        else:
            if not self.method or not isinstance(self.method, str):
                raise ValueError(
                    "Если websocket=False → method обязателен (непустая строка)"
                )

        # Нормализуем tags
        if self.tags is None:
            self.tags = []
