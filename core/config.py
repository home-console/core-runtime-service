"""
Конфигурация Core Runtime.

Минимальные настройки.
"""

import os
from dataclasses import dataclass
from typing import Optional, List


@dataclass
class Config:
    """Конфигурация Core Runtime."""
    # Тип адаптера: "sqlite" или "postgresql"
    storage_type: str = "sqlite"
    
    # Путь к файлу БД (для SQLite)
    db_path: str = "data/runtime.db"

    # PostgreSQL настройки
    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "homeconsole"
    pg_user: str = "postgres"
    pg_password: str = ""
    pg_dsn: Optional[str] = None  # Если указан, остальные pg_* игнорируются

    # Тайм-аут для shutdown (секунды)
    shutdown_timeout: int = 10
    
    # Тайм-аут для вызовов сервисов (секунды)
    # Защита от зависших вызовов плагинов
    service_call_timeout: float = 30.0
    
    # Rate limiting настройки
    # Отключить rate limiting для разработки (НЕ использовать в production!)
    rate_limiting_enabled: bool = True
    # Максимум запросов в окне времени
    rate_limit_requests: int = 100
    # Окно времени в секундах
    rate_limit_window: int = 60

    # Security / Environment
    # "development" | "production"
    env: str = "development"

    # CORS
    # В production обязательно ограничить домены.
    cors_allowed_origins: List[str] = None  # type: ignore[assignment]

    # CSRF protection (для cookie-based auth)
    csrf_enabled: bool = True
    csrf_cookie_name: str = "csrf_token"
    csrf_header_name: str = "X-CSRF-Token"

    # Cookies
    # В production обычно: secure=True, samesite="strict|lax", domain=None/your-domain
    cookies_secure: Optional[bool] = None  # None => auto (https => True)
    cookies_samesite: str = "lax"  # "lax" | "strict" | "none"
    cookies_domain: Optional[str] = "localhost"

    # Security headers / CSP
    # "relaxed" (dev) | "strict" (prod)
    csp_mode: str = "relaxed"

    # Logging
    # "text" | "json"
    log_format: str = "text"

    def validate(self) -> None:
        """
        Валидировать конфигурацию.
        
        Raises:
            ValueError: если конфигурация невалидна
        """
        # Валидация storage_type
        if self.storage_type not in ("sqlite", "postgresql"):
            raise ValueError(
                f"storage_type must be 'sqlite' or 'postgresql', got: {self.storage_type!r}"
            )
        
        # Валидация SQLite параметров
        if self.storage_type == "sqlite":
            if not self.db_path:
                raise ValueError("db_path must be non-empty for SQLite storage")
            if not isinstance(self.db_path, str):
                raise ValueError(f"db_path must be string, got: {type(self.db_path).__name__}")
        
        # Валидация PostgreSQL параметров
        if self.storage_type == "postgresql":
            if not self.pg_dsn:
                # Если DSN не указан, проверяем отдельные параметры
                if not self.pg_database:
                    raise ValueError("pg_database must be non-empty for PostgreSQL storage")
                if not self.pg_user:
                    raise ValueError("pg_user must be non-empty for PostgreSQL storage")
                if not isinstance(self.pg_host, str):
                    raise ValueError(f"pg_host must be string, got: {type(self.pg_host).__name__}")
                if not isinstance(self.pg_port, int) or self.pg_port <= 0 or self.pg_port > 65535:
                    raise ValueError(
                        f"pg_port must be integer between 1 and 65535, got: {self.pg_port}"
                    )
        
        # Валидация shutdown_timeout
        if not isinstance(self.shutdown_timeout, int) or self.shutdown_timeout <= 0:
            raise ValueError(
                f"shutdown_timeout must be positive integer, got: {self.shutdown_timeout}"
            )

        # env
        if self.env not in ("development", "production"):
            raise ValueError(f"env must be 'development' or 'production', got: {self.env!r}")

        # cors_allowed_origins
        if self.cors_allowed_origins is None:
            # Default for dev
            self.cors_allowed_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
        if not isinstance(self.cors_allowed_origins, list) or not all(isinstance(x, str) for x in self.cors_allowed_origins):
            raise ValueError("cors_allowed_origins must be list[str]")

        # csrf config
        if not isinstance(self.csrf_cookie_name, str) or not self.csrf_cookie_name:
            raise ValueError("csrf_cookie_name must be non-empty string")
        if not isinstance(self.csrf_header_name, str) or not self.csrf_header_name:
            raise ValueError("csrf_header_name must be non-empty string")

        # cookies_samesite
        if self.cookies_samesite not in ("lax", "strict", "none"):
            raise ValueError("cookies_samesite must be one of: lax, strict, none")
        # allow empty string => None for domain
        if self.cookies_domain == "":
            self.cookies_domain = None

        # csp_mode
        if self.csp_mode not in ("relaxed", "strict"):
            raise ValueError("csp_mode must be 'relaxed' or 'strict'")

        # log_format
        if self.log_format not in ("text", "json"):
            raise ValueError("log_format must be 'text' or 'json'")

    @classmethod
    def from_env(cls) -> "Config":
        """
        Создать конфигурацию из переменных окружения.
        
        Raises:
            ValueError: если конфигурация невалидна
        """
        cors_raw = os.getenv("RUNTIME_CORS_ALLOWED_ORIGINS")
        cors_allowed = None
        if cors_raw:
            cors_allowed = [x.strip() for x in cors_raw.split(",") if x.strip()]

        config = cls(
            storage_type=os.getenv("RUNTIME_STORAGE_TYPE", "sqlite"),
            db_path=os.getenv("RUNTIME_DB_PATH", "data/runtime.db"),
            pg_host=os.getenv("RUNTIME_PG_HOST", "localhost"),
            pg_port=int(os.getenv("RUNTIME_PG_PORT", "5432")),
            pg_database=os.getenv("RUNTIME_PG_DATABASE", "homeconsole"),
            pg_user=os.getenv("RUNTIME_PG_USER", "postgres"),
            pg_password=os.getenv("RUNTIME_PG_PASSWORD", ""),
            pg_dsn=os.getenv("RUNTIME_PG_DSN"),
            shutdown_timeout=int(os.getenv("RUNTIME_SHUTDOWN_TIMEOUT", "10")),
            service_call_timeout=float(os.getenv("RUNTIME_SERVICE_CALL_TIMEOUT", "30.0")),
            rate_limiting_enabled=os.getenv("RUNTIME_RATE_LIMITING_ENABLED", "true").lower() == "true",
            rate_limit_requests=int(os.getenv("RUNTIME_RATE_LIMIT_REQUESTS", "100")),
            rate_limit_window=int(os.getenv("RUNTIME_RATE_LIMIT_WINDOW", "60")),
            env=os.getenv("RUNTIME_ENV", "development").lower(),
            cors_allowed_origins=cors_allowed,
            csrf_enabled=os.getenv("RUNTIME_CSRF_ENABLED", "true").lower() == "true",
            csrf_cookie_name=os.getenv("RUNTIME_CSRF_COOKIE_NAME", "csrf_token"),
            csrf_header_name=os.getenv("RUNTIME_CSRF_HEADER_NAME", "X-CSRF-Token"),
            cookies_secure=(None if os.getenv("RUNTIME_COOKIES_SECURE") is None else os.getenv("RUNTIME_COOKIES_SECURE", "true").lower() == "true"),
            cookies_samesite=os.getenv("RUNTIME_COOKIES_SAMESITE", "lax").lower(),
            cookies_domain=os.getenv("RUNTIME_COOKIES_DOMAIN", "localhost"),
            csp_mode=os.getenv("RUNTIME_CSP_MODE", "relaxed").lower(),
            log_format=os.getenv("RUNTIME_LOG_FORMAT", "text").lower(),
        )
        config.validate()
        return config
