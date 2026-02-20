"""
AuthModule — модуль для HTTP endpoints аутентификации и авторизации.

Декларирует HTTP endpoints для admin auth API.
Services (admin.auth.*) остаются в AdminModule.
Это разделение: HTTP ownership vs Service ownership.
"""

from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint


class AuthModule(RuntimeModule):
    """
    Модуль HTTP endpoints для аутентификации.
    
    Владеет HTTP декларациями для auth API.
    НЕ дублирует services - они в AdminModule.
    """

    @property
    def name(self) -> str:
        """Уникальное имя модуля."""
        return "auth"

    async def register(self) -> None:
        """
        Регистрация HTTP endpoints для аутентификации.
        
        Декларирует только HTTP → service mapping.
        Services уже зарегистрированы в AdminModule.
        """
        # Auth initialization & login endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/initialize",
            service="admin.auth.initialize",
            description="Initialize auth system (first-time setup)"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/login",
            service="admin.auth.login",
            description="Login with credentials"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/refresh",
            service="admin.auth.refresh",
            description="Refresh access token"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/auth/me",
            service="admin.auth.me",
            description="Get current user info"
        ))
        
        # Password management endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/password/set",
            service="admin.auth.set_password",
            description="Set user password (admin only)"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/password/change",
            service="admin.auth.change_password",
            description="Change own password"
        ))
        
        # Session management endpoints
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/auth/sessions",
            service="admin.auth.list_sessions",
            description="List user sessions"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/sessions/revoke",
            service="admin.auth.revoke_session",
            description="Revoke a session"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/sessions/revoke-all",
            service="admin.auth.revoke_all_sessions",
            description="Revoke all user sessions"
        ))
        
        # API key management endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/api-keys",
            service="admin.auth.create_api_key",
            description="Create API key"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/auth/api-keys",
            service="admin.auth.list_api_keys",
            description="List API keys"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/api-keys/revoke",
            service="admin.auth.revoke_api_key",
            description="Revoke API key"
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/api-keys/rotate",
            service="admin.auth.rotate_api_key",
            description="Rotate API key"
        ))
        
        # User management endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/users",
            service="admin.auth.create_user",
            description="Create user"
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/auth/users",
            service="admin.auth.list_users",
            description="List users"
        ))

    async def start(self) -> None:
        """Запуск модуля - ничего не требуется."""
        pass

    async def stop(self) -> None:
        """Остановка модуля - ничего не требуется."""
        pass
