"""
Pydantic validation models for security-critical endpoints.

Цель:
- Закрыть A03 (Injection) через строгую валидацию входных данных
- Дать единый слой проверки входа ДО вызова service_registry

Важно:
- Мы валидируем только ключевые публичные/админские endpoints, чтобы не ломать
  существующие плагины и динамические JSON payload'ы.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

try:
    # pydantic v2
    from pydantic import BaseModel, Field, ValidationError
except Exception:  # pragma: no cover
    # pydantic v1 fallback
    from pydantic import BaseModel, Field, ValidationError  # type: ignore


class AdminAuthLoginBody(BaseModel):
    user_id: str = Field(min_length=1)
    password: str = Field(min_length=1)
    client_ip: Optional[str] = None
    user_agent: Optional[str] = None


class AdminAuthRefreshBody(BaseModel):
    refresh_token: Optional[str] = None


class AdminAuthInitializeBody(BaseModel):
    # user_id может быть сгенерен на backend, но если передан — должен быть строкой
    user_id: Optional[str] = None
    username: Optional[str] = None
    password: str = Field(min_length=1)


class AdminDevicesSetStateBody(BaseModel):
    # Поддерживаем оба формата: {state: {...}} или плоский объект {on: true}
    state: Optional[Dict[str, Any]] = None
    on: Optional[bool] = None
    power: Optional[str] = None


SERVICE_BODY_MODELS: Dict[str, Type[BaseModel]] = {
    "admin.auth.login": AdminAuthLoginBody,
    "admin.auth.refresh": AdminAuthRefreshBody,
    "admin.auth.initialize": AdminAuthInitializeBody,
    "admin.devices.set_state": AdminDevicesSetStateBody,
    "devices.set_state": AdminDevicesSetStateBody,
}


def _model_dump(m: BaseModel) -> Dict[str, Any]:
    if hasattr(m, "model_dump"):  # pydantic v2
        return m.model_dump(exclude_none=True)  # type: ignore[attr-defined]
    return m.dict(exclude_none=True)  # type: ignore[no-any-return]


def validate_body_for_service(service_name: str, body: Any) -> Any:
    """
    Валидирует body для конкретного service_name.

    Returns:
        - исходный body (если модель не определена)
        - валидированный dict (если модель определена)

    Raises:
        ValueError: если body не проходит валидацию
    """
    model = SERVICE_BODY_MODELS.get(service_name)
    if model is None:
        return body
    if not isinstance(body, dict):
        raise ValueError("invalid_body")
    try:
        if hasattr(model, "model_validate"):  # type: ignore[attr-defined]
            obj = model.model_validate(body)  # type: ignore[attr-defined]
        else:  # pragma: no cover
            obj = model.parse_obj(body)  # type: ignore[attr-defined]
    except ValidationError as e:
        raise ValueError({"validation_errors": e.errors()})
    return _model_dump(obj)

