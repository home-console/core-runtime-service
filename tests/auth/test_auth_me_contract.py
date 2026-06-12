"""
Контракт GET /api/v1/auth/me ↔ frontend AuthUser.

Этот тест ловит регрессию вида «handler вернул {id,email,name,role}, а
response_model требует user_id/username/...». До фикса (2026-06-12) endpoint
имел response_model=UserDto, у которого поле user_id обязательно — поэтому
любой запрос к /auth/me валился 500 ResponseValidationError.

Тест держит контракт под двумя углами:
1. Shape, который реально возвращает auth_me(), парсится в AuthMeResponse
   без ValidationError (имитация того, что делает FastAPI с response_model).
2. Названия полей AuthMeResponse совпадают с frontend AuthUser interface
   (`platform-home-console/packages/auth-core/src/types.ts`): id, email,
   role, name. Так мы синхронно ловим переименования с обеих сторон.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.runtime.auth_contextvars import set_current_auth_context
from modules.api.auth.constants import AUTH_USERS_NAMESPACE
from modules.api.schemas import AuthMeResponse, UserDto
from modules.auth.handlers import auth_me


class FakeStorage:
    def __init__(self) -> None:
        self._d: dict[str, dict[str, object]] = {}

    async def get(self, ns: str, key: str):  # noqa: ANN201
        return self._d.get(ns, {}).get(key)

    async def set(self, ns: str, key: str, value: object) -> None:
        self._d.setdefault(ns, {})[key] = value


@pytest.fixture
def rt() -> SimpleNamespace:
    return SimpleNamespace(storage=FakeStorage())


@pytest.fixture(autouse=True)
def _reset_auth_context():
    """Гарантируем чистый ContextVar между тестами."""
    set_current_auth_context(None)
    yield
    set_current_auth_context(None)


@pytest.mark.asyncio
async def test_auth_me_returns_shape_compatible_with_response_model(rt) -> None:
    """Регрессия: результат auth_me() должен пройти через AuthMeResponse.

    Раньше handler возвращал {id,email,name,role}, а response_model=UserDto
    требовала user_id → FastAPI кидал ResponseValidationError на каждый
    логин-флоу.
    """
    await rt.storage.set(
        AUTH_USERS_NAMESPACE,
        "admin",
        {"username": "Администратор", "is_admin": True, "scopes": ["*"]},
    )
    set_current_auth_context(
        SimpleNamespace(user_id="admin", is_admin=True, scopes=["*"])
    )

    result = await auth_me(rt)

    # Главная проверка: pydantic-парсинг не должен упасть.
    # Если bridge/route_binding в _normalize_api_result обернёт result в
    # {"ok": True, "result": ...} — это будет другая регрессия и тест
    # должен честно упасть.
    dto = AuthMeResponse.model_validate(result)
    assert dto.id == "admin"
    assert dto.email == "Администратор"
    assert dto.name == "Администратор"
    assert dto.role == "admin"


@pytest.mark.asyncio
async def test_auth_me_non_admin_role_is_none(rt) -> None:
    """Для не-админа role должен быть None (а не пустая строка/missing)."""
    await rt.storage.set(
        AUTH_USERS_NAMESPACE,
        "alice",
        {"username": "Alice", "is_admin": False, "scopes": ["devices.read"]},
    )
    set_current_auth_context(
        SimpleNamespace(user_id="alice", is_admin=False, scopes=["devices.read"])
    )

    result = await auth_me(rt)
    dto = AuthMeResponse.model_validate(result)
    assert dto.role is None
    assert dto.id == "alice"


@pytest.mark.asyncio
async def test_auth_me_without_context_raises_unauthorized(rt) -> None:
    """Нет auth context → UnauthorizedError (а не 500)."""
    from core.exceptions import UnauthorizedError

    set_current_auth_context(None)
    with pytest.raises(UnauthorizedError):
        await auth_me(rt)


@pytest.mark.asyncio
async def test_auth_me_user_missing_in_storage_raises_unauthorized(rt) -> None:
    """Контекст есть, но юзера нет в storage → UnauthorizedError."""
    from core.exceptions import UnauthorizedError

    set_current_auth_context(
        SimpleNamespace(user_id="ghost", is_admin=False, scopes=[])
    )
    with pytest.raises(UnauthorizedError):
        await auth_me(rt)


def test_auth_me_response_fields_match_frontend_authuser_contract() -> None:
    """Поля AuthMeResponse строго совпадают с frontend AuthUser interface.

    Источник правды: platform-home-console/packages/auth-core/src/types.ts
        interface AuthUser { id: string; email: string; role?: string; name?: string }

    Если кто-то добавит поле в backend DTO без согласования с frontend —
    тест честно упадёт и заставит обновить обе стороны или сделать поле
    Optional с разумным default.
    """
    expected = {"id", "email", "role", "name"}
    actual = set(AuthMeResponse.model_fields.keys())
    assert actual == expected, (
        f"AuthMeResponse расходится с frontend AuthUser:\n"
        f"  backend поля:  {sorted(actual)}\n"
        f"  frontend ждёт: {sorted(expected)}\n"
        f"  → синхронизируй с platform-home-console/packages/auth-core/src/types.ts"
    )

    # id/email обязательны и должны быть str-совместимы; role/name — Optional[str].
    required = {n for n, f in AuthMeResponse.model_fields.items() if f.is_required()}
    assert required == {"id", "email"}, (
        f"id и email должны быть обязательными, остальные — Optional: {required}"
    )


def test_user_dto_remains_admin_shape_unchanged() -> None:
    """Гарантия: UserDto не «уплыл» к AuthMeResponse-форме.

    UserDto используется в admin endpoints (/api/v1/admin/auth/users), у
    которых другой контракт: user_id/username/scopes/is_admin/created_at.
    Если кто-то унифицирует UserDto с AuthMeResponse — фронт-сторона
    админки сломается, поэтому держим shape отдельным тестом.
    """
    fields = set(UserDto.model_fields.keys())
    must_have = {"user_id", "username", "scopes", "is_admin", "created_at"}
    assert must_have.issubset(fields), (
        f"UserDto потерял admin-поля: ожидаются {sorted(must_have)}, "
        f"есть {sorted(fields)}"
    )
    # И наоборот: frontend-specific полей (id/email/name/role) в UserDto быть не должно.
    forbidden = {"id", "email", "name", "role"}
    assert not (forbidden & fields), (
        f"UserDto не должен содержать frontend-AuthUser поля {forbidden & fields}; "
        f"для /auth/me есть отдельный AuthMeResponse."
    )
