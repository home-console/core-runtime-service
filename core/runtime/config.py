"""
Конфигурация Core Runtime.

Минимальные настройки.
Extensibility: modules_config, plugins_dir, orchestration_backend.

Security конфигурация (CORS/CSRF/CSP/cookies) вынесена в security_config.py.
"""

from dataclasses import dataclass, field
import re
from typing import List, Mapping, Optional

from core.runtime.security_config import SecurityConfig


def _get_security_attr(config: SecurityConfig | None, name: str, default: object) -> object:
    if config is None:
        return default
    return getattr(config, name, default)


def _get_int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, str(default))
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid integer env var {key}={raw!r}") from e


def _get_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, str(default))
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError) as e:
        raise ValueError(f"Invalid float env var {key}={raw!r}") from e

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

    # Storage v3: Dual-mode configuration (physical isolation of vault storage)
    # "single" (default, backward compatible) or "dual" (separate vault storage)
    storage_mode: str = "single"

    # Vault storage type (required in dual mode): "sqlite" or "postgresql"
    vault_storage_type: Optional[str] = None

    # Vault SQLite path (used if vault_storage_type == "sqlite")
    vault_db_path: Optional[str] = None

    # Vault PostgreSQL DSN (used if vault_storage_type == "postgresql")
    vault_pg_dsn: Optional[str] = None

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

    # Environment
    # "development" | "production"
    env: str = "development"

    # Logging
    # "text" | "json"
    log_format: str = "text"

    # Security configuration (вынесено из core)
    security_config: Optional[SecurityConfig] = None

    # Extensibility: модули и плагины из конфига (override hardcoded lists)
    # RUNTIME_MODULES: comma-separated "name" or "name:required" (e.g. "api:true,admin:true,agent:false")
    # Если пусто — используется дефолтный APP_MODULES из main.py
    modules_config: Optional[str] = None
    # RUNTIME_PLUGINS_DIR: путь к папке плагинов (относительно cwd или абсолютный)
    plugins_dir: Optional[str] = None
    # RUNTIME_ORCHESTRATION_BACKEND: "docker" (default) | "none" (no-op для headless)
    orchestration_backend: str = "docker"
    # RUNTIME_MODULE_PATH_PREFIX: префикс для discovery модулей (default "modules")
    module_path_prefix: str = "modules"
    
    # URL-префикс HTTP API: литерал /api/v1 в HttpEndpoint заменяется на api_url_prefix.
    api_url_prefix: str = "/api/v1"
    # Префикс дерева WebSocket (отдельно от REST). Литерал /api/v1 в путях WS
    # заменяется на ws_url_prefix (см. modules.api.route_binding).
    ws_url_prefix: str = "/ws"

    # Marketplace
    # Default registry index URL (e.g. "https://marketplace.homeconsole.dev/registry/index.json")
    marketplace_registry_url: str = ""

    # Runtime semver advertised by this deployment (used for compatibility checks like plugin min_runtime).
    # NOTE: keep in sync with release tagging / deployment config.
    runtime_version: str = "0.1.0"

    def validate(self) -> None:
        """
        Валидировать конфигурацию.

        Raises:
            ValueError: если конфигурация невалидна
        """
        # Валидация storage_mode
        if self.storage_mode not in ("single", "dual"):
            raise ValueError(
                f"storage_mode must be 'single' or 'dual', got: {self.storage_mode!r}"
            )

        # Валидация storage_type
        if self.storage_type not in ("sqlite", "postgresql"):
            raise ValueError(
                f"storage_type must be 'sqlite' or 'postgresql', got: {self.storage_type!r}"
            )

        # Валидация SQLite параметров
        if self.storage_type == "sqlite":
            if not self.db_path:
                raise ValueError("db_path must be non-empty for SQLite storage")

        # Валидация PostgreSQL параметров
        if self.storage_type == "postgresql":
            if not self.pg_dsn:
                # Если DSN не указан, проверяем отдельные параметры
                if not self.pg_database:
                    raise ValueError(
                        "pg_database must be non-empty for PostgreSQL storage"
                    )
                if not self.pg_user:
                    raise ValueError("pg_user must be non-empty for PostgreSQL storage")
                if self.pg_port <= 0 or self.pg_port > 65535:
                    raise ValueError(
                        f"pg_port must be integer between 1 and 65535, got: {self.pg_port}"
                    )

        # Storage v3: Dual-mode validation
        if self.storage_mode == "dual":
            if not self.vault_storage_type:
                raise ValueError(
                    "storage_mode='dual' requires vault_storage_type to be set ('sqlite' or 'postgresql')"
                )

            if self.vault_storage_type not in ("sqlite", "postgresql"):
                raise ValueError(
                    f"vault_storage_type must be 'sqlite' or 'postgresql', got: {self.vault_storage_type!r}"
                )

            # Validate vault SQLite config
            if self.vault_storage_type == "sqlite":
                if not self.vault_db_path:
                    raise ValueError(
                        "storage_mode='dual' with vault_storage_type='sqlite' requires vault_db_path"
                    )

            # Validate vault PostgreSQL config
            if self.vault_storage_type == "postgresql":
                if not self.vault_pg_dsn:
                    raise ValueError(
                        "storage_mode='dual' with vault_storage_type='postgresql' requires vault_pg_dsn"
                    )

        # Валидация shutdown_timeout
        if self.shutdown_timeout <= 0:
            raise ValueError(
                f"shutdown_timeout must be positive integer, got: {self.shutdown_timeout}"
            )

        # env
        if self.env not in ("development", "production"):
            raise ValueError(
                f"env must be 'development' or 'production', got: {self.env!r}"
            )

        # trust_proxy_headers
        # Значение определяется в dataclass и в from_env (парсер возвращает
        # bool), поэтому явная проверка типа здесь избыточна.

        # security_config compatibility
        security_cfg = self.security_config
        cors_allowed_origins = _get_security_attr(security_cfg, "cors_allowed_origins", None)
        if cors_allowed_origins is None:
            default_origins = [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
            ]
            if security_cfg is not None:
                security_cfg.cors_allowed_origins = list(default_origins)

        csrf_cookie_name = str(_get_security_attr(security_cfg, "csrf_cookie_name", "csrf_token"))
        if not csrf_cookie_name:
            raise ValueError("csrf_cookie_name must be non-empty string")

        csrf_header_name = str(_get_security_attr(security_cfg, "csrf_header_name", "X-CSRF-Token"))
        if not csrf_header_name:
            raise ValueError("csrf_header_name must be non-empty string")

        cookies_samesite = str(_get_security_attr(security_cfg, "cookies_samesite", "lax")).lower()
        if cookies_samesite not in ("lax", "strict", "none"):
            raise ValueError("cookies_samesite must be one of: lax, strict, none")

        cookies_domain = _get_security_attr(security_cfg, "cookies_domain", None)
        if cookies_domain == "" and security_cfg is not None:
            security_cfg.cookies_domain = None

        csp_mode = str(_get_security_attr(security_cfg, "csp_mode", "relaxed")).lower()
        if csp_mode not in ("relaxed", "strict"):
            raise ValueError("csp_mode must be 'relaxed' or 'strict'")

        # log_format
        if self.log_format not in ("text", "json"):
            raise ValueError("log_format must be 'text' or 'json'")

        # orchestration_backend
        if self.orchestration_backend not in ("docker", "none"):
            raise ValueError("orchestration_backend must be 'docker' or 'none'")

        if not self.module_path_prefix:
            raise ValueError("module_path_prefix must be non-empty string")

        if not self.runtime_version:
            raise ValueError("runtime_version must be non-empty string")
        if not re.match(
            r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", str(self.runtime_version)
        ):
            raise ValueError(
                "runtime_version must be semantic version X.Y.Z with optional pre-release suffix"
            )

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Config":
        """
        Создать конфигурацию из переменных окружения.

        Env vars:
        - RUNTIME_STORAGE_MODE: "single" (default) or "dual"
        - RUNTIME_VAULT_STORAGE_TYPE: "sqlite" or "postgresql" (required in dual mode)
        - RUNTIME_VAULT_DB_PATH: path to vault SQLite file (required if vault_storage_type="sqlite")
        - RUNTIME_VAULT_PG_DSN: PostgreSQL DSN for vault (required if vault_storage_type="postgresql")
        - MARKETPLACE_REGISTRY_URL: default marketplace registry index URL (optional)
        - RUNTIME_VERSION: semver of this core-runtime-service deployment (optional)

        Raises:
            ValueError: если конфигурация невалидна
        """
        # Security config вынесен в отдельный класс
        security_config = SecurityConfig.from_env(env)

        if env is None:
            # Keep the dependency at the boundary: only this helper reads process env.
            import os

            env = os.environ

        config = cls(
            storage_type=env.get("RUNTIME_STORAGE_TYPE", "sqlite"),
            db_path=env.get("RUNTIME_DB_PATH", "data/runtime.db"),
            pg_host=env.get("RUNTIME_PG_HOST", "localhost"),
            pg_port=_get_int(env, "RUNTIME_PG_PORT", 5432),
            pg_database=env.get("RUNTIME_PG_DATABASE", "homeconsole"),
            pg_user=env.get("RUNTIME_PG_USER", "postgres"),
            pg_password=env.get("RUNTIME_PG_PASSWORD", ""),
            pg_dsn=env.get("RUNTIME_PG_DSN"),
            shutdown_timeout=_get_int(env, "RUNTIME_SHUTDOWN_TIMEOUT", 10),
            service_call_timeout=_get_float(env, "RUNTIME_SERVICE_CALL_TIMEOUT", 30.0),
            rate_limiting_enabled=env.get("RUNTIME_RATE_LIMITING_ENABLED", "true").lower()
            == "true",
            rate_limit_requests=_get_int(env, "RUNTIME_RATE_LIMIT_REQUESTS", 100),
            rate_limit_window=_get_int(env, "RUNTIME_RATE_LIMIT_WINDOW", 60),
            env=env.get("RUNTIME_ENV", "development").lower(),
            log_format=env.get("RUNTIME_LOG_FORMAT", "text").lower(),
            security_config=security_config,
            # Storage v3: Dual-mode configuration
            storage_mode=env.get("RUNTIME_STORAGE_MODE", "single").lower(),
            vault_storage_type=env.get("RUNTIME_VAULT_STORAGE_TYPE"),
            vault_db_path=env.get("RUNTIME_VAULT_DB_PATH"),
            vault_pg_dsn=env.get("RUNTIME_VAULT_PG_DSN"),
            # Extensibility
            modules_config=env.get("RUNTIME_MODULES"),
            plugins_dir=env.get("RUNTIME_PLUGINS_DIR"),
            orchestration_backend=env.get("RUNTIME_ORCHESTRATION_BACKEND", "docker").lower(),
            module_path_prefix=env.get("RUNTIME_MODULE_PATH_PREFIX", "modules"),
            marketplace_registry_url=str(env.get("MARKETPLACE_REGISTRY_URL", "")).strip(),
            runtime_version=str(env.get("RUNTIME_VERSION", "0.1.0")).strip() or "0.1.0",
            api_url_prefix=str(env.get("RUNTIME_API_PREFIX", "/api/v1")).strip() or "/api/v1",
            ws_url_prefix=(
                str(env.get("RUNTIME_WS_PREFIX", "/ws")).strip() or "/ws"
            ),
        )
        config.validate()
        return config
