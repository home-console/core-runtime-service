"""
Policy Engine — централизованный движок авторизационных политик.

Централизованный слой авторизационных проверок (из ServiceRegistry)
в отдельный слой, который можно использовать независимо.

PolicyEngine инкапсулирует:
- Проверку прав доступа к ресурсам
- Фильтрацию результатов по политикам
- Enforcement политик для операций
- Интеграцию с RequestContext и SystemContext
"""

from typing import Any, Dict, List, Iterable, Optional, Callable, Awaitable
from abc import ABC, abstractmethod

from core.errors import ForbiddenError, NotFoundError
from core.auth_contextvars import get_current_auth_context


class Policy(ABC):
    """
    Базовый класс для политик доступа к ресурсам.
    
    Политика определяет правила доступа к конкретному типу ресурса
    (например, device, device_mapping, user и т.д.).
    """
    
    @abstractmethod
    def enforce(self, ctx: Any, obj: Any) -> None:
        """
        Применить политику к объекту.
        
        Args:
            ctx: RequestContext или SystemContext
            obj: объект ресурса для проверки
            
        Raises:
            ForbiddenError: если доступ запрещён
            NotFoundError: если объект не должен быть раскрыт
        """
        pass
    
    @abstractmethod
    def filter(self, ctx: Any, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Отфильтровать список объектов по политике.
        
        Args:
            ctx: RequestContext или SystemContext
            items: итерируемый список объектов
            
        Returns:
            Отфильтрованный список объектов, к которым есть доступ
        """
        pass


class DevicePolicy(Policy):
    """Политика доступа к устройствам: owner/shared или admin."""
    
    def enforce(self, ctx: Any, obj: Any) -> None:
        """Применить политику к устройству."""
        if obj is None:
            raise NotFoundError("device not found")
        
        # SystemContext и админы имеют полный доступ
        if self._is_privileged(ctx):
            return
        
        user_id = getattr(ctx, "user_id", None) if ctx else None
        if not user_id:
            raise NotFoundError("device not found")
        
        if isinstance(obj, dict):
            owner_id = obj.get("owner_id")
            if owner_id and owner_id == user_id:
                return
            shared_with = obj.get("shared_with")
            if isinstance(shared_with, list) and user_id in shared_with:
                return
        
        # Не раскрываем существование ресурса
        raise NotFoundError("device not found")
    
    def filter(self, ctx: Any, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Отфильтровать устройства по политике."""
        if ctx is None:
            return list(items)
        
        result: List[Dict[str, Any]] = []
        for item in items:
            try:
                self.enforce(ctx, item)
                result.append(item)
            except Exception:
                # Скрываем чужие объекты
                continue
        return result
    
    def _is_privileged(self, ctx: Any) -> bool:
        """Проверить, имеет ли контекст привилегированный доступ."""
        if not ctx:
            return False
        
        # SystemContext всегда привилегирован
        from core.system_context import is_system_context
        if is_system_context(ctx):
            return True
        
        try:
            if getattr(ctx, "is_admin", False):
                return True
            scopes = getattr(ctx, "scopes", set()) or set()
            return ("admin.*" in scopes) or ("*" in scopes)
        except Exception:
            return False


class AdminOnlyPolicy(Policy):
    """Политика только для админов (device_mapping, external_inventory и т.д.)."""
    
    def enforce(self, ctx: Any, obj: Any) -> None:
        """Применить политику: только админы."""
        if ctx is None:
            raise ForbiddenError("forbidden: admin operation requires context")
        
        if self._is_privileged(ctx):
            return
        
        raise ForbiddenError("forbidden")
    
    def filter(self, ctx: Any, items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Отфильтровать: только админы видят все."""
        if ctx is None:
            return []
        
        if self._is_privileged(ctx):
            return list(items)
        
        return []
    
    def _is_privileged(self, ctx: Any) -> bool:
        """Проверить, имеет ли контекст привилегированный доступ."""
        if not ctx:
            return False
        
        from core.system_context import is_system_context
        if is_system_context(ctx):
            return True
        
        try:
            if getattr(ctx, "is_admin", False):
                return True
            scopes = getattr(ctx, "scopes", set()) or set()
            return ("admin.*" in scopes) or ("*" in scopes)
        except Exception:
            return False


class PolicyEngine:
    """
    Движок авторизационных политик.
    
    Централизованный слой для авторизационных проверок,
    независимый от ServiceRegistry.
    
    Использование:
        policy_engine = PolicyEngine()
        policy_engine.enforce_policy(ctx, "device", device_obj)
        filtered = policy_engine.filter_with_policy(ctx, "device", devices_list)
    """
    
    def __init__(self):
        """Инициализация PolicyEngine с регистрацией стандартных политик."""
        self._policies: Dict[str, Policy] = {}
        
        # Регистрируем стандартные политики
        self.register_policy("device", DevicePolicy())
        self.register_policy("device_mapping", AdminOnlyPolicy())
        self.register_policy("external_inventory", AdminOnlyPolicy())
    
    def register_policy(self, resource_type: str, policy: Policy) -> None:
        """
        Зарегистрировать политику для типа ресурса.
        
        Args:
            resource_type: тип ресурса (например, "device", "user")
            policy: экземпляр Policy
        """
        self._policies[resource_type] = policy
    
    def get_policy(self, resource_type: str) -> Optional[Policy]:
        """
        Получить политику для типа ресурса.
        
        Args:
            resource_type: тип ресурса
            
        Returns:
            Policy или None если политика не найдена
        """
        return self._policies.get(resource_type)
    
    def enforce_policy(self, ctx: Any, resource_type: str, obj: Any) -> None:
        """
        Применить политику к объекту.
        
        Args:
            ctx: RequestContext или SystemContext (может быть None для internal calls)
            resource_type: тип ресурса
            obj: объект для проверки
            
        Raises:
            ForbiddenError: если доступ запрещён
            NotFoundError: если объект не должен быть раскрыт
        """
        # Если ctx is None, считаем trusted internal call (для обратной совместимости)
        # В будущем можно ужесточить и требовать SystemContext
        if ctx is None:
            return
        
        policy = self.get_policy(resource_type)
        if policy is None:
            # Неизвестный ресурс — пока пропускаем (минимально инвазивно)
            return
        
        policy.enforce(ctx, obj)
    
    def filter_with_policy(
        self,
        ctx: Any,
        resource_type: str,
        items: Iterable[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Отфильтровать список объектов по политике.
        
        Args:
            ctx: RequestContext или SystemContext (может быть None для internal calls)
            resource_type: тип ресурса
            items: итерируемый список объектов
            
        Returns:
            Отфильтрованный список объектов
        """
        if ctx is None:
            return list(items)
        
        policy = self.get_policy(resource_type)
        if policy is None:
            # Неизвестный ресурс — возвращаем как есть
            return list(items)
        
        return policy.filter(ctx, items)
    
    def enforce_admin(self, ctx: Any) -> None:
        """
        Требует админ-привилегии.
        
        Args:
            ctx: RequestContext или SystemContext
            
        Raises:
            ForbiddenError: если нет админ-прав или ctx=None
        """
        if ctx is None:
            raise ForbiddenError("forbidden: admin operation requires context")
        
        if self._is_privileged(ctx):
            return
        
        raise ForbiddenError("forbidden")
    
    def is_privileged(self, ctx: Any) -> bool:
        """
        Проверить, имеет ли контекст привилегированный доступ.
        
        Args:
            ctx: RequestContext или SystemContext
            
        Returns:
            True если контекст имеет привилегированный доступ
        """
        return self._is_privileged(ctx)
    
    def _is_privileged(self, ctx: Any) -> bool:
        """Внутренний метод для проверки привилегий."""
        if not ctx:
            return False
        
        # SystemContext всегда привилегирован
        from core.system_context import is_system_context
        if is_system_context(ctx):
            return True
        
        try:
            if getattr(ctx, "is_admin", False):
                return True
            scopes = getattr(ctx, "scopes", set()) or set()
            return ("admin.*" in scopes) or ("*" in scopes)
        except Exception:
            return False
    
    def current_context(self) -> Any:
        """
        Получить текущий RequestContext из contextvars.
        
        Returns:
            RequestContext или None
        """
        return get_current_auth_context()


# Глобальный экземпляр PolicyEngine (singleton)
_global_policy_engine: Optional[PolicyEngine] = None


def get_policy_engine() -> PolicyEngine:
    """
    Получить глобальный экземпляр PolicyEngine.
    
    Returns:
        PolicyEngine
    """
    global _global_policy_engine
    if _global_policy_engine is None:
        _global_policy_engine = PolicyEngine()
    return _global_policy_engine


def set_policy_engine(engine: PolicyEngine) -> None:
    """
    Установить глобальный экземпляр PolicyEngine (для тестирования).
    
    Args:
        engine: экземпляр PolicyEngine
    """
    global _global_policy_engine
    _global_policy_engine = engine
