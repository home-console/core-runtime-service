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
from core.runtime_module import RuntimeModule
from core.http_registry import HttpEndpoint, EndpointAuthConfig
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
        def wrap_domain(fn: Any) -> Any:
            """Wrap handler to pass runtime as first argument."""
            return lambda *args, **kw: fn(self.runtime, *args, **kw)
        
        services_config = [
            # Bootstrap (read-only system state, no auth required)
            ("auth.bootstrap", wrap_domain(auth_bootstrap), False),
            
            # Public services (no auth required)
            ("auth.initialize", wrap_domain(auth_initialize), False),
            ("auth.login", wrap_domain(auth_login), False),
            ("auth.refresh", wrap_domain(auth_refresh), False),
            ("auth.logout", wrap_domain(auth_logout), False),
            ("auth.me", wrap_domain(auth_me), False),
            
            # Protected services (admin-only)
            ("admin.auth.create_api_key", wrap_domain(auth_create_api_key), True),
            ("admin.auth.list_api_keys", wrap_domain(auth_list_api_keys), True),
            ("admin.auth.create_user", wrap_domain(auth_create_user), True),
            ("admin.auth.list_users", wrap_domain(auth_list_users), True),
            ("admin.auth.set_password", wrap_domain(auth_set_password), True),
            ("admin.auth.change_password", wrap_domain(auth_change_password), True),
            ("admin.auth.list_sessions", wrap_domain(auth_list_sessions), True),
            ("admin.auth.revoke_session", wrap_domain(auth_revoke_session), True),
            ("admin.auth.revoke_all_sessions", wrap_domain(auth_revoke_all_sessions), True),
            ("admin.auth.revoke_api_key", wrap_domain(auth_revoke_api_key), True),
            ("admin.auth.rotate_api_key", wrap_domain(auth_rotate_api_key), True),
        ]
        
        for service_name, handler, admin_only in services_config:
            try:
                services = self.context.services
                if hasattr(services, "register_with_acl"):
                    await services.register_with_acl(service_name, handler, admin_only=admin_only)
                else:
                    await services.register(service_name, handler)
            except ValueError:
                # Service already registered (best-effort)
                pass
            except Exception as e:
                self.runtime.logger.warning(f"Failed to register {service_name}: {e}")
        
        # --- Register HTTP Endpoints ---
        # Bootstrap endpoint (check if system initialized)
        self.context.http.register(HttpEndpoint(
            method="GET",
            path="/auth/v1/bootstrap",
            service="auth.bootstrap",
            description="Check if system is initialized (bootstrap status)",
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
