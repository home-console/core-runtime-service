"""
API Key Authentication — boundary-layer для ApiModule и AdminModule.

Это boundary-layer: auth логика НЕ проникает в CoreRuntime, RuntimeModule,
ServiceRegistry или доменные модули. Всё изолировано на уровне HTTP.

Архитектура:
- RequestContext передаётся через request.state (FastAPI)
- validate_api_key() проверяет ключ и возвращает RequestContext
- check_service_scope() проверяет права на вызов сервиса
- API keys хранятся в runtime.storage namespace "auth_api_keys"

Future-ready:
- Структура подготовлена для добавления users, sessions, OAuth
- RequestContext может быть расширен без изменения сигнатур сервисов
"""

from dataclasses import dataclass
from typing import Any, Optional, List, Dict
from fastapi import Request, HTTPException, status

# Storage namespace для API keys
AUTH_API_KEYS_NAMESPACE = "auth_api_keys"


@dataclass
class RequestContext:
    """
    Контекст авторизации для HTTP запроса.
    
    Передаётся через request.state в FastAPI.
    Не проникает в CoreRuntime или доменные модули.
    """
    subject: str  # Идентификатор субъекта (например, "api_key:key_id")
    scopes: List[str]  # Список разрешений (например, ["devices.read", "devices.write"])
    is_admin: bool  # Административные права
    source: str  # Источник авторизации (например, "api_key")


async def validate_api_key(runtime: Any, api_key: str) -> Optional[RequestContext]:
    """
    Валидирует API Key и возвращает RequestContext.
    
    Args:
        runtime: экземпляр CoreRuntime
        api_key: API ключ из заголовка Authorization: Bearer <key>
    
    Returns:
        RequestContext если ключ валиден, None если не найден
    
    Raises:
        HTTPException: если ключ найден, но данные повреждены
    """
    if not api_key or not api_key.strip():
        return None
    
    try:
        # Получаем данные ключа из storage
        key_data = await runtime.storage.get(AUTH_API_KEYS_NAMESPACE, api_key)
        
        if key_data is None:
            return None
        
        # Проверяем структуру данных
        if not isinstance(key_data, dict):
            # Повреждённые данные - логируем и возвращаем None
            try:
                await runtime.service_registry.call(
                    "logger.log",
                    level="warning",
                    message=f"Invalid API key data structure for key: {api_key[:8]}...",
                    module="api"
                )
            except Exception:
                pass
            return None
        
        # Извлекаем данные
        subject = key_data.get("subject", f"api_key:{api_key[:8]}")
        scopes = key_data.get("scopes", [])
        is_admin = key_data.get("is_admin", False)
        
        # Нормализуем scopes
        if not isinstance(scopes, list):
            scopes = []
        
        return RequestContext(
            subject=subject,
            scopes=scopes,
            is_admin=is_admin,
            source="api_key"
        )
    
    except Exception as e:
        # Ошибка при чтении storage - логируем и возвращаем None
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="error",
                message=f"Error validating API key: {e}",
                module="api"
            )
        except Exception:
            pass
        return None


def extract_api_key_from_header(request: Request) -> Optional[str]:
    """
    Извлекает API Key из заголовка Authorization: Bearer <key>.
    
    Args:
        request: FastAPI Request
    
    Returns:
        API key или None если заголовок отсутствует/неверный формат
    """
    auth_header = request.headers.get("Authorization", "")
    
    if not auth_header:
        return None
    
    # Поддерживаем формат "Bearer <token>"
    parts = auth_header.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    
    api_key = parts[1].strip()
    if not api_key:
        return None
    
    return api_key


def check_service_scope(context: Optional[RequestContext], service_name: str) -> bool:
    """
    Проверяет, есть ли у контекста права на вызов сервиса.
    
    Правила:
    - Если context is None (нет авторизации) → False
    - Если is_admin=True → True (полный доступ)
    - Если service_name начинается с "admin." → требуется is_admin=True
    - Иначе проверяем scopes по паттерну: <namespace>.<action> или <namespace>.*
    
    Args:
        context: RequestContext или None
        service_name: имя сервиса (например, "devices.list", "admin.v1.runtime")
    
    Returns:
        True если есть права, False если нет
    """
    if context is None:
        return False
    
    # Администраторы имеют полный доступ
    if context.is_admin:
        return True
    
    # Административные сервисы требуют admin прав
    if service_name.startswith("admin."):
        return False
    
    # Извлекаем namespace и action из service_name
    # Формат: "namespace.action" или "namespace.sub.action"
    parts = service_name.split(".", 1)
    if len(parts) < 2:
        # Нестандартный формат - требуем admin
        return False
    
    namespace = parts[0]
    action = parts[1]
    
    # Проверяем scopes
    # Поддерживаем:
    # - "namespace.action" (точное совпадение)
    # - "namespace.*" (все действия в namespace)
    # - "*" (все действия)
    required_scope_exact = f"{namespace}.{action}"
    required_scope_wildcard = f"{namespace}.*"
    
    if "*" in context.scopes:
        return True
    
    if required_scope_exact in context.scopes:
        return True
    
    if required_scope_wildcard in context.scopes:
        return True
    
    return False


async def get_request_context(request: Request) -> Optional[RequestContext]:
    """
    Получает RequestContext из request.state.
    
    Используется в handlers для доступа к контексту авторизации.
    
    Args:
        request: FastAPI Request
    
    Returns:
        RequestContext или None если не установлен
    """
    return getattr(request.state, "auth_context", None)


async def require_auth_middleware(request: Request, call_next):
    """
    FastAPI middleware для проверки API Key авторизации.
    
    Извлекает API Key из заголовка, валидирует его и сохраняет RequestContext
    в request.state.auth_context.
    
    Если ключ не передан или невалиден, context будет None.
    Проверка прав выполняется в handlers перед вызовом service_registry.call().
    
    Args:
        request: FastAPI Request
        call_next: следующий middleware/handler
    
    Returns:
        Response
    """
    # Извлекаем API Key
    api_key = extract_api_key_from_header(request)
    
    # Получаем runtime из app.state (устанавливается в ApiModule)
    runtime = getattr(request.app.state, "runtime", None)
    
    context = None
    if api_key and runtime:
        try:
            context = await validate_api_key(runtime, api_key)
        except Exception:
            # При ошибке валидации context остаётся None
            context = None
    
    # Сохраняем context в request.state
    request.state.auth_context = context
    
    # Продолжаем обработку запроса
    response = await call_next(request)
    return response
