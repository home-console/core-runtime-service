import logging
"""
Authorization Policy Layer — единая точка авторизационных проверок.

Цель: Единая точка, через которую система отвечает на вопрос:
"Разрешено ли выполнить действие?"

Архитектура:
- Использует RequestContext из auth.py
- Scope-based authorization (endpoint_auth_config / ServiceAuthConfig)
- Resource-Based Authorization с ACL (ownership + shared_with)
- Self-service проверки для auth операций
- НЕ логирует
- НЕ мутирует состояние
"""

from typing import Optional, Dict, Any, Set, Sequence
import asyncio
from modules.api.auth import RequestContext
logger = logging.getLogger(__name__)
from core.service.models import ServiceAuthConfig
from core.http.models import EndpointAuthConfig


class AuthorizationError(Exception):
    """Исключение при отказе в авторизации."""
    pass


def _service_auth_config_from_runtime(runtime: Optional[Any], action: str) -> Optional[ServiceAuthConfig]:
    """
    Получить декларативную auth_config для runtime-сервиса.

    runtime: CoreRuntime или facade, который содержит service_registry (или сам является service_registry).
    """
    if runtime is None:
        return None
    reg = getattr(runtime, "service_registry", None) or getattr(runtime, "services", None) or runtime
    getter_sync = getattr(reg, "get_auth_config_sync", None)
    if callable(getter_sync):
        try:
            return getter_sync(action)
        except Exception:
            return None

    # Backward-compatible fallback: async getter exists but we're in sync context.
    # Do not attempt to bridge event loops here.
    return None


def _scope_satisfies(ctx_scopes: Set[str], required_scope: str) -> bool:
    """
    Проверка required_scope по текущей семантике scope-based auth:
    - точное совпадение required_scope
    - wildcard по namespace: "<namespace>.*"
    - глобальный wildcard "*" проверяется снаружи (для единообразия логики)
    """
    if required_scope in ctx_scopes:
        return True
    if "." in required_scope:
        namespace = required_scope.split(".", 1)[0]
        if f"{namespace}.*" in ctx_scopes:
            return True
    return False


def check(
    ctx: Optional[RequestContext],
    action: str,
    resource: Optional[Dict[str, Any]] = None,
    *,
    runtime: Optional[Any] = None,
    endpoint_auth_config: Optional[EndpointAuthConfig] = None,
) -> bool:
    """
    Проверяет, разрешено ли выполнить действие.
    
    Поддерживает Resource-Based Authorization с ACL (Ownership + Shared Resources).
    
    Args:
        ctx: RequestContext или None
        action: действие (например, "devices.get", "admin.v1.runtime")
        resource: ресурс с метаданными (owner_id, shared_with, user_id и т.д.)
    
    Returns:
        True если разрешено, False если запрещено
    
    Правила проверки действия:
    - Если ctx is None → False (кроме admin.auth.create_api_key при отсутствии ключей и oauth-provider.*)
    - Если is_admin=True → True (полный доступ)
    - Если action начинается с "admin." → требуется "admin.*"
    - Иначе проверяем mapping: action → required scope
    
    Правила проверки ресурса (если resource предоставлен):
    - Ownership: если owner_id == ctx.user_id → разрешено
    - Shared access: если ctx.user_id в shared_with → разрешено
    - Self-service: для auth операций разрешено если target_user_id == ctx.user_id
    - Admin override: если ctx.is_admin → разрешено
    """
    # Валидация входных параметров
    if not action or not isinstance(action, str):
        return False
    
    if resource is not None and not isinstance(resource, dict):
        return False
    # Декларативная authz для HTTP endpoints (самый приоритетный источник правды).
    if endpoint_auth_config is not None and endpoint_auth_config.public:
        return True

    # Специальный случай: создание первого API key разрешено без авторизации
    # Проверяем через resource, который передаётся из handler
    if action == "admin.auth.create_api_key" and resource and resource.get("allow_first_key"):
        return True
    
    # Legacy public rules removed: declare public via EndpointAuthConfig/ServiceAuthConfig.

    # Декларативная authz для сервисов (SDK-first).
    svc_auth = _service_auth_config_from_runtime(runtime, action)
    if svc_auth and svc_auth.public:
        return True

    # Креды пользователя: доступны любому авторизованному пользователю (свои креды)
    if action.startswith("user.v1.credentials.") and ctx and ctx.user_id:
        return True
    
    # Нет контекста → нет доступа
    if ctx is None:
        return False
    
    # Администраторы имеют полный доступ (включая все ресурсы)
    if ctx.is_admin:
        return True
    
    # Полный wildcard даёт доступ ко всему (но проверяем ресурс отдельно)
    # SECURITY FIX: Используем Set для O(1) проверки и защиты от timing attacks
    has_wildcard_scope = "*" in ctx.scopes
    
    # Проверяем права на действие (scope-based)
    action_allowed = False

    if action.startswith("admin."):
        # Phase 4: admin.* actions uniformly require "admin.*" (or "admin.read"/"admin.write" from endpoint_auth_config).
        # All explicit admin endpoints now declare auth_config, so the fallback handles the rest.
        required_scopes_from_endpoint: list[str] = []
        if endpoint_auth_config and endpoint_auth_config.required_scopes:
            required_scopes_from_endpoint = [
                s
                for s in endpoint_auth_config.required_scopes
                if isinstance(s, str) and s
            ]

        if required_scopes_from_endpoint:
            action_allowed = has_wildcard_scope or any(
                _scope_satisfies(ctx.scopes, s) for s in required_scopes_from_endpoint
            )
        elif svc_auth and svc_auth.required_scopes:
            required_scopes = [
                s for s in svc_auth.required_scopes if isinstance(s, str) and s
            ]
            action_allowed = has_wildcard_scope or any(
                _scope_satisfies(ctx.scopes, s) for s in required_scopes
            ) if required_scopes else has_wildcard_scope
        else:
            # Fallback: все admin.* действия требуют admin.*
            action_allowed = "admin.*" in ctx.scopes or has_wildcard_scope
    else:
        # Non-admin actions: use declarative auth_config (SDK-first).
        required_scopes_from_endpoint = []
        if endpoint_auth_config and endpoint_auth_config.required_scopes:
            required_scopes_from_endpoint = [
                s
                for s in endpoint_auth_config.required_scopes
                if isinstance(s, str) and s
            ]

        if required_scopes_from_endpoint:
            action_allowed = has_wildcard_scope or any(
                _scope_satisfies(ctx.scopes, s) for s in required_scopes_from_endpoint
            )
        elif svc_auth and svc_auth.required_scopes:
            # OR-semantics: достаточно одного scope из списка.
            required_scopes = [
                s for s in svc_auth.required_scopes if isinstance(s, str) and s
            ]
            if not required_scopes:
                action_allowed = has_wildcard_scope
            else:
                action_allowed = has_wildcard_scope or any(
                    _scope_satisfies(ctx.scopes, s) for s in required_scopes
                )
        else:
            # Phase 4: no ACTION_SCOPE_MAP fallback — fail-closed without wildcards.
            action_allowed = has_wildcard_scope
    
    # Если нет прав на действие → запрещаем
    if not action_allowed:
        return False
    
    # Проверяем права на ресурс (Resource-Based Authorization)
    if resource:
        # SECURITY FIX: Добавлены проверки на None для ctx.user_id
        # 1. Ownership проверка
        if "owner_id" in resource:
            owner_id = resource["owner_id"]
            if ctx.user_id and ctx.user_id == owner_id:
                return True  # Владелец имеет доступ
        
        # 2. Shared access (ACL)
        if "shared_with" in resource:
            shared_with = resource["shared_with"]
            if isinstance(shared_with, list) and ctx.user_id and ctx.user_id in shared_with:
                return True  # Пользователь в списке shared_with
        
        # 3. Self-service для auth операций
        if action in ["admin.auth.change_password", "admin.auth.set_password", 
                      "admin.auth.revoke_all_sessions", "admin.auth.list_sessions"]:
            target_user_id = resource.get("user_id")
            if target_user_id and ctx.user_id and ctx.user_id == target_user_id:
                return True  # Пользователь управляет своим аккаунтом
        
        # 4. Если ресурс указан, но нет совпадений → запрещаем
        # (кроме случаев, когда resource необязателен для действия)
        # Для некоторых действий resource может быть None (например, devices.list)
        # В этом случае проверяем только действие
        if "owner_id" in resource or "shared_with" in resource or "user_id" in resource:
            # Ресурс указан, но нет доступа → запрещаем
            return False
    
    # Если нет проверок ресурса или они пройдены → разрешаем
    return True


def require(
    ctx: Optional[RequestContext],
    action: str,
    resource: Optional[Dict[str, Any]] = None,
    runtime: Optional[Any] = None,
    *,
    endpoint_auth_config: Optional[EndpointAuthConfig] = None,
) -> None:
    """
    Требует разрешения на выполнение действия.
    
    Вызывает check() и бросает AuthorizationError если доступ запрещён.
    
    Args:
        ctx: RequestContext или None
        action: действие
        resource: ресурс (принимается, но не используется)
        runtime: опциональный экземпляр CoreRuntime для audit logging
    
    Raises:
        AuthorizationError: если доступ запрещён
    """
    if not check(
        ctx,
        action,
        resource,
        runtime=runtime,
        endpoint_auth_config=endpoint_auth_config,
    ):
        # Audit logging отказов в авторизации
        if runtime:
            try:
                from modules.api.auth.audit import audit_log_auth_event
                
                subject = ctx.user_id if ctx and ctx.user_id else (ctx.subject if ctx else "anonymous")
                identifier = subject[:16] + "..." if len(subject) > 16 else subject
                
                # Конвертируем Set в List для JSON сериализации
                scopes_list = list(ctx.scopes) if ctx and ctx.scopes else []
                
                # Логируем асинхронно, если возможно
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        # Если loop уже запущен, создаём задачу
                        asyncio.create_task(audit_log_auth_event(
                            runtime,
                            "authorization_denied",
                            identifier,
                            {
                                "action": action,
                                "user_id": ctx.user_id if ctx else None,
                                "scopes": scopes_list,
                                "is_admin": ctx.is_admin if ctx else False,
                            },
                            success=False
                        ))
                    else:
                        # Если loop не запущен, запускаем синхронно
                        loop.run_until_complete(audit_log_auth_event(
                            runtime,
                            "authorization_denied",
                            identifier,
                            {
                                "action": action,
                                "user_id": ctx.user_id if ctx else None,
                                "scopes": scopes_list,
                                "is_admin": ctx.is_admin if ctx else False,
                            },
                            success=False
                        ))
                except Exception:
                    # Если не удалось залогировать, не падаем
                    logger.warning("Unhandled exception", exc_info=True)
            except Exception:
                # Игнорируем ошибки audit logging
                logger.warning("Unhandled exception", exc_info=True)
        
        raise AuthorizationError(f"Authorization failed for action: {action}")


def get_required_scope(action: str) -> Optional[str]:
    """
    DEPRECATED: use get_required_scopes() instead.

    Legacy single-scope lookup. Returns the first required scope or
    "admin.*" for admin actions.
    """
    scopes = get_required_scopes(action)
    return scopes[0] if scopes else None


def get_required_scopes(
    action: str,
    *,
    runtime: Optional[Any] = None,
    endpoint_auth_config: Optional[EndpointAuthConfig] = None,
) -> Sequence[str]:
    """
    Возвращает required scopes для действия.

    Используется для документирования, отладки и Inspector.

    Приоритет источников:
    1. endpoint_auth_config.required_scopes (если передан)
    2. ServiceAuthConfig из service_registry (через runtime)
    3. Fallback: "admin.*" для admin.* действий, иначе пусто

    Args:
        action: действие (например, "devices.get", "admin.v1.runtime")
        runtime: опциональный CoreRuntime для lookup ServiceAuthConfig
        endpoint_auth_config: опциональная декларативная auth конфигурация

    Returns:
        Список required scopes (может быть пустым)
    """
    if endpoint_auth_config and endpoint_auth_config.required_scopes:
        return [s for s in endpoint_auth_config.required_scopes if isinstance(s, str) and s]

    svc_auth = _service_auth_config_from_runtime(runtime, action)
    if svc_auth and svc_auth.required_scopes:
        return [s for s in svc_auth.required_scopes if isinstance(s, str) and s]

    if action.startswith("admin."):
        return ["admin.*"]

    return []
