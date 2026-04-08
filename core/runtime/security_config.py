"""
SecurityConfig — конфигурация web-edge безопасности.

Вынесено из core.runtime.config для соблюдения границ ядра.
CORS/CSRF/CSP/cookies принадлежат app-layer, не минимальному kernel.
"""

from dataclasses import dataclass
from typing import List, Mapping, Optional


@dataclass
class SecurityConfig:
    """
    Конфигурация web-edge безопасности.

    Атрибуты:
        cors_allowed_origins: список разрешённых CORS origin'ов
        csrf_enabled: включена ли CSRF защита
        csrf_cookie_name: имя CSRF cookie
        csrf_header_name: имя CSRF заголовка
        cookies_secure: флаг secure для cookies
        cookies_samesite: SameSite атрибут cookies
        cookies_domain: домен для cookies
        csp_mode: режим Content Security Policy
        trust_proxy_headers: доверять ли proxy заголовкам
    """
    cors_allowed_origins: List[str]
    csrf_enabled: bool = True
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"
    cookies_secure: Optional[bool] = None
    cookies_samesite: str = "lax"
    cookies_domain: Optional[str] = "localhost"
    csp_mode: str = "relaxed"
    trust_proxy_headers: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "SecurityConfig":
        """
        Создать SecurityConfig из переменных окружения.

        Returns:
            Экземпляр SecurityConfig
        """
        if env is None:
            import os

            env = os.environ

        cors_raw = env.get("RUNTIME_CORS_ALLOWED_ORIGINS")
        cors_allowed = None
        if cors_raw:
            cors_allowed = [x.strip() for x in cors_raw.split(",") if x.strip()]

        return cls(
            cors_allowed_origins=cors_allowed
            if cors_allowed is not None
            else ["http://localhost:3000", "http://127.0.0.1:3000"],
            csrf_enabled=env.get("RUNTIME_CSRF_ENABLED", "true").lower() == "true",
            csrf_cookie_name=env.get("RUNTIME_CSRF_COOKIE_NAME", "csrf_token"),
            csrf_header_name=env.get("RUNTIME_CSRF_HEADER_NAME", "X-CSRF-Token"),
            cookies_secure=(
                None
                if env.get("RUNTIME_COOKIES_SECURE") is None
                else env.get("RUNTIME_COOKIES_SECURE", "true").lower() == "true"
            ),
            cookies_samesite=env.get("RUNTIME_COOKIES_SAMESITE", "lax").lower(),
            cookies_domain=env.get("RUNTIME_COOKIES_DOMAIN", "localhost"),
            csp_mode=env.get("RUNTIME_CSP_MODE", "relaxed").lower(),
            trust_proxy_headers=env.get("RUNTIME_TRUST_PROXY_HEADERS", "false").lower()
            == "true",
        )
