"""
AuthModule — Identity & Security boundary.

Owns:
  1. admin.auth.* services (login, refresh, me, password, sessions, api-keys, users)
  2. HTTP endpoints → admin.auth.* service mapping
  3. ACL configuration for auth services

Admin UI (AdminModule) uses auth services but doesn't own them.
This separation ensures identity can evolve independently:
  - MFA support
  - OAuth / WebAuthn
  - Multi-server auth
  - SSO integration

Identity is not mixed with Control Plane (admin UI).
"""

from typing import Any
from core.runtime.runtime_module import RuntimeModule
from core.http.models import HttpEndpoint, EndpointAuthConfig
from .handlers import (
    auth_create_api_key,
    auth_list_api_keys,
    auth_create_user,
    auth_list_users,
    auth_initialize,
    auth_login,
    auth_refresh,
    auth_logout,
    auth_set_password,
    auth_change_password,
    auth_list_sessions,
    auth_revoke_session,
    auth_revoke_all_sessions,
    auth_revoke_api_key,
    auth_rotate_api_key,
    auth_me,
    auth_bootstrap,
    auth_dev_credentials,
)


class AuthModule(RuntimeModule):
    """
    Auth Module — Identity boundary.
    
    Responsibilities:
      1. Register admin.auth.* services
      2. Configure HTTP endpoints for auth API
      3. Set ACL rules for auth services
      4. Public services: login, refresh, me, initialize
      5. Protected services: password, sessions, api-keys, users (admin-only)
    """

    @property
    def name(self) -> str:
        """Unique module name."""
        return "auth"

    async def register(self) -> None:
        """
        Register auth services and HTTP endpoints.
        
        Services registered with ACL:
        - Public (no auth needed): initialize, login, refresh, me
        - Protected (admin only): password, sessions, api-keys, users
        
        HTTP endpoints registered for each service.
        """
        
        # --- Register Services with ACL ---
        services_config = [
            # Bootstrap (read-only system state, no auth required)
            ("auth.bootstrap", auth_bootstrap, False),
            # Dev-only: api_base_url + api_key для веба (только при DEV_CREDENTIALS=1)
            ("auth.dev_credentials", auth_dev_credentials, False),

            # Public services (no auth required)
            ("auth.initialize", auth_initialize, False),
            ("auth.login", auth_login, False),
            ("auth.refresh", auth_refresh, False),
            ("auth.logout", auth_logout, False),
            ("auth.me", auth_me, False),

            # Protected services (admin-only)
            ("admin.auth.create_api_key", auth_create_api_key, True),
            ("admin.auth.list_api_keys", auth_list_api_keys, True),
            ("admin.auth.create_user", auth_create_user, True),
            ("admin.auth.list_users", auth_list_users, True),
            ("admin.auth.set_password", auth_set_password, True),
            ("admin.auth.change_password", auth_change_password, True),
            ("admin.auth.list_sessions", auth_list_sessions, True),
            ("admin.auth.revoke_session", auth_revoke_session, True),
            ("admin.auth.revoke_all_sessions", auth_revoke_all_sessions, True),
            ("admin.auth.revoke_api_key", auth_revoke_api_key, True),
            ("admin.auth.rotate_api_key", auth_rotate_api_key, True),
        ]

        for service_name, handler, admin_only in services_config:
            try:
                await self.register_runtime_service(
                    service_name,
                    handler,
                    admin_only=admin_only,
                )
            except Exception as e:
                logger = getattr(self.runtime, "logger", None) if self.runtime else None
                if logger:
                    logger.warning(f"Failed to register {service_name}: {e}")
        
        # --- Register HTTP Endpoints ---
        # Bootstrap endpoint (check if system initialized)
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/auth/v1/bootstrap",
            service="auth.bootstrap",
            description="Check if system is initialized (bootstrap status)",
            auth_config=EndpointAuthConfig(public=True)
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/auth/v1/dev-credentials",
            service="auth.dev_credentials",
            description="Dev-only: api_base_url and optional api_key for web (when DEV_CREDENTIALS=1)",
            auth_config=EndpointAuthConfig(public=True)
        ))
        
        # Auth initialization & login endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/auth/v1/initialize",
            service="auth.initialize",
            description="Initialize auth system (first-time setup)",
            auth_config=EndpointAuthConfig(public=True)
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/auth/v1/login",
            service="auth.login",
            description="Login with credentials",
            auth_config=EndpointAuthConfig(public=True)
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/auth/v1/refresh",
            service="auth.refresh",
            description="Refresh access token",
            auth_config=EndpointAuthConfig(public=True)
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/auth/v1/logout",
            service="auth.logout",
            description="Logout and clear session",
            auth_config=EndpointAuthConfig(public=True)
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/auth/v1/me",
            service="auth.me",
            description="Get current user info",
            auth_config=EndpointAuthConfig(public=True)
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/password/set",
            service="admin.auth.set_password",
            description="Set user password (admin only)",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/password/change",
            service="admin.auth.change_password",
            description="Change own password",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        
        # Session management endpoints
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/auth/sessions",
            service="admin.auth.list_sessions",
            description="List user sessions",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/sessions/revoke",
            service="admin.auth.revoke_session",
            description="Revoke a session",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/sessions/revoke-all",
            service="admin.auth.revoke_all_sessions",
            description="Revoke all user sessions",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        
        # API key management endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/api-keys",
            service="admin.auth.create_api_key",
            description="Create API key",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/auth/api-keys",
            service="admin.auth.list_api_keys",
            description="List API keys",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/api-keys/revoke",
            service="admin.auth.revoke_api_key",
            description="Revoke API key",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/api-keys/rotate",
            service="admin.auth.rotate_api_key",
            description="Rotate API key",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        
        # User management endpoints
        self.context.http.register(HttpEndpoint(
            method="POST",
            path="/admin/v1/auth/users",
            service="admin.auth.create_user",
            description="Create user",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/admin/v1/auth/users",
            service="admin.auth.list_users",
            description="List users",
            auth_config=EndpointAuthConfig(required_scopes=["admin.*"]),
        ))

    async def start(self) -> None:
        """Запуск модуля - ничего не требуется."""
        pass

    async def stop(self) -> None:
        """Остановка модуля - ничего не требуется."""
        pass
