"""
Доменные адаптеры для HTTP endpoints.

REFACTORING: Проблема 6 - выносим доменную логику из route_binding.py
в отдельные адаптеры, которые могут быть использованы декларативно.

Каждый адаптер инкапсулирует:
- Логику получения resource для resource-based authorization
- Специфичную обработку параметров для домена
- Валидацию и преобразование данных
"""

from typing import Any, Dict, Optional
from fastapi import Request


class DomainAdapter:
    """Базовый класс для доменных адаптеров."""
    
    async def extract_resource(
        self,
        request: Request,
        service_name: str,
        runtime: Any,
        context: Optional[Any] = None,
        body: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Извлечь resource для resource-based authorization.
        
        Args:
            request: FastAPI Request
            service_name: имя сервиса
            runtime: экземпляр CoreRuntime
            context: RequestContext (опционально)
            body: тело запроса (опционально)
            **kwargs: дополнительные параметры
            
        Returns:
            Dict с метаданными ресурса (owner_id, shared_with, user_id и т.д.) или None
        """
        return None
    
    async def extract_params(
        self,
        request: Request,
        body: Optional[Dict[str, Any]],
        path_params: Dict[str, Any],
        query_params: Dict[str, Any],
        service_name: str,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Извлечь и преобразовать параметры для вызова сервиса.
        
        Args:
            request: FastAPI Request
            body: тело запроса (если есть)
            path_params: параметры пути
            query_params: query-параметры
            service_name: имя сервиса
            **kwargs: дополнительные параметры
            
        Returns:
            Dict с параметрами для service_registry.call()
        """
        params: Dict[str, Any] = {}
        params.update(path_params)
        params.update(query_params)
        if body is not None:
            params["body"] = body
        return params


class DevicesAdapter(DomainAdapter):
    """Адаптер для devices endpoints."""
    
    async def extract_resource(
        self,
        request: Request,
        service_name: str,
        runtime: Any,
        **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Извлечь resource для devices.get и devices.set_state.
        
        Для этих endpoints нужно получить device и проверить owner_id/shared_with.
        """
        if service_name not in ["devices.get", "devices.set_state", "product_api.v1.devices.set_state"]:
            return None
        
        device_id = request.path_params.get("id") or request.path_params.get("device_id")
        if not device_id:
            return None
        
        try:
            device = await runtime.service_registry.call("devices.get", device_id)
            if isinstance(device, dict):
                resource: Dict[str, Any] = {}
                if "owner_id" in device:
                    resource["owner_id"] = device["owner_id"]
                if "shared_with" in device:
                    resource["shared_with"] = device["shared_with"]
                return resource
        except Exception:
            # Если не удалось получить device, возвращаем None
            # route_binding обработает это как отсутствие resource
            pass
        
        return None


class AuthAdapter(DomainAdapter):
    """Адаптер для auth endpoints."""
    
    async def extract_resource(
        self,
        request: Request,
        service_name: str,
        runtime: Any,
        context: Optional[Any] = None,
        body: Optional[Dict[str, Any]] = None,
        **kwargs: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Извлечь resource для auth endpoints.
        
        Специальные случаи:
        - admin.auth.create_api_key: проверка первого ключа
        - admin.auth.change_password, set_password, revoke_all_sessions, list_sessions: user_id из body
        """
        resource: Dict[str, Any] = {}
        
        # Специальный случай: создание первого API ключа
        if service_name == "admin.auth.create_api_key" and context is None:
            try:
                keys = await runtime.storage.list_keys("auth_api_keys")
                first_key_flag = await runtime.storage.get("auth_config", "first_key_created")
                if len(keys) == 0 and first_key_flag is None:
                    try:
                        await runtime.storage.set("auth_config", "first_key_created", True)
                        resource["allow_first_key"] = True
                    except Exception:
                        keys_retry = await runtime.storage.list_keys("auth_api_keys")
                        if len(keys_retry) == 0:
                            resource["allow_first_key"] = True
            except Exception:
                pass
        
        # Self-service endpoints: извлекаем user_id из body
        if service_name in [
            "admin.auth.change_password",
            "admin.auth.set_password",
            "admin.auth.revoke_all_sessions",
            "admin.auth.list_sessions"
        ]:
            if body is None:
                try:
                    body = await request.json()
                except Exception:
                    body = None
            
            if isinstance(body, dict):
                user_id = body.get("user_id")
                if user_id:
                    resource["user_id"] = user_id
        
        return resource if resource else None
    
    async def extract_params(
        self,
        request: Request,
        body: Optional[Dict[str, Any]],
        path_params: Dict[str, Any],
        query_params: Dict[str, Any],
        service_name: str,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Извлечь параметры для auth endpoints с учётом спец-логики.
        
        Для некоторых auth endpoints нужно извлечь user_id из body для resource check.
        """
        params: Dict[str, Any] = {}
        params.update(path_params)
        params.update(query_params)
        
        # Для auth endpoints, которые требуют body для resource check
        if service_name in [
            "admin.auth.change_password",
            "admin.auth.set_password",
            "admin.auth.revoke_all_sessions",
            "admin.auth.list_sessions"
        ]:
            if body is None:
                try:
                    body = await request.json()
                except Exception:
                    body = None
            
            if isinstance(body, dict):
                user_id = body.get("user_id")
                if user_id:
                    # Сохраняем user_id для resource check
                    params["_resource_user_id"] = user_id
        
        if body is not None:
            params["body"] = body
        
        # Специальные случаи для login/refresh/me
        if service_name in ["admin.auth.login", "admin.auth.refresh"]:
            params["request"] = request
            params["response"] = kwargs.get("response")
        elif service_name == "admin.auth.me":
            params["request"] = request
        
        return params


class OAuthAdapter(DomainAdapter):
    """Адаптер для OAuth endpoints."""
    
    async def extract_params(
        self,
        request: Request,
        body: Optional[Dict[str, Any]],
        path_params: Dict[str, Any],
        query_params: Dict[str, Any],
        service_name: str,
        **kwargs: Any
    ) -> Dict[str, Any]:
        """
        Извлечь параметры для OAuth endpoints с учётом спец-логики.
        
        OAuth endpoints требуют перепаковки параметров из body в отдельные параметры.
        """
        params: Dict[str, Any] = {}
        params.update(path_params)
        params.update(query_params)
        
        if body and isinstance(body, dict):
            if service_name == "oauth_yandex.configure":
                # Перепаковываем body в отдельные параметры
                params["client_id"] = body.get("client_id", "")
                params["client_secret"] = body.get("client_secret", "")
                params["redirect_uri"] = body.get("redirect_uri", "")
                if "scope" in body:
                    params["scope"] = body.get("scope")
            elif service_name == "oauth_yandex.exchange_code":
                # Перепаковываем code из body
                params["code"] = body.get("code", "")
            else:
                # Для остальных OAuth endpoints просто передаём body
                params["body"] = body
        
        return params


# Реестр адаптеров по имени домена
_DOMAIN_ADAPTERS: Dict[str, DomainAdapter] = {
    "devices": DevicesAdapter(),
    "auth": AuthAdapter(),
    "oauth": OAuthAdapter(),
}


def get_domain_adapter(domain: Optional[str]) -> Optional[DomainAdapter]:
    """
    Получить доменный адаптер по имени домена.
    
    Args:
        domain: имя домена (например, "devices", "auth", "oauth")
        
    Returns:
        DomainAdapter или None если адаптер не найден
    """
    if domain is None:
        return None
    return _DOMAIN_ADAPTERS.get(domain)


def register_domain_adapter(domain: str, adapter: DomainAdapter) -> None:
    """
    Зарегистрировать доменный адаптер.
    
    Args:
        domain: имя домена
        adapter: экземпляр DomainAdapter
    """
    _DOMAIN_ADAPTERS[domain] = adapter
