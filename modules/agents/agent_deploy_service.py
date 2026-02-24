"""
AgentDeployService — SSH‑bootstrap агента на удалённом хосте.

Через существующий SSH credential:
- генерирует одноразовый enrollment token (TTL 10 минут);
- загружает installer script на удалённый хост;
- запускает installer с параметрами: enrollment_token, core_url.

Логирование — через structured logger (service `logger.log`), без утечки секретов.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple
import asyncio
import os
import shlex
import uuid

from core.credentials.repository import CredentialRepository
from core.logger_helper import info as log_info
from modules.ssh.ssh_execution_service import SSHExecutionService


CredentialWithSecret = Tuple[Any, bytes]


@dataclass
class AgentDeployConfig:
    """
    Конфигурация деплоя агента.
    """

    installer_relative_path: str = "installer_templates/agent_install.sh"
    remote_base_dir: str = "/tmp"


class AgentDeployService:
    """
    Сервис SSH‑деплоя агента.

    Ожидает, что в runtime уже инициализированы:
    - storage_manager + secret_store (для CredentialRepository);
    - agent_manager (AgentEnrollmentManager) c generate_enrollment_token().
    """

    def __init__(self, runtime: Any, config: AgentDeployConfig | None = None) -> None:
        self._runtime = runtime
        self._config = config or AgentDeployConfig()
        self._ssh = SSHExecutionService()

    async def _get_credential_with_secret(self, credential_id: str) -> CredentialWithSecret:
        """
        Получить (Credential, secret_bytes) из CredentialRepository.
        """
        storage_manager = getattr(self._runtime, "storage_manager", None)
        secret_store = getattr(self._runtime, "secret_store", None)
        if storage_manager is None or secret_store is None:
            raise ValueError("Credential storage not configured (storage_manager or secret_store missing)")

        repo = CredentialRepository(storage_manager=storage_manager, secret_store=secret_store)
        pair = await repo.get_with_secret(credential_id)
        if pair is None:
            raise ValueError(f"Credential {credential_id} not found")
        return pair

    async def _generate_enrollment_token(self, agent_name: str) -> str:
        """
        Сгенерировать одноразовый enrollment token через AgentEnrollmentManager.
        """
        agent_manager = getattr(self._runtime, "agent_manager", None)
        if agent_manager is None:
            raise ValueError("AgentEnrollmentManager is not initialized on runtime (runtime.agent_manager)")

        # Новый метод generate_enrollment_token возвращает HMAC‑подписанную строку
        token = await agent_manager.generate_enrollment_token(agent_name)
        return token

    def _resolve_installer_path(self) -> Path:
        """
        Найти локальный installer script в modules/agents/installer_templates.
        """
        base_dir = Path(__file__).resolve().parent
        installer_path = base_dir / self._config.installer_relative_path
        if not installer_path.is_file():
            raise FileNotFoundError(f"Agent installer script not found at {installer_path}")
        return installer_path

    def _compute_core_url(self) -> str:
        """
        Определить CORE_URL для удалённого агента.

        Приоритет:
        1. Переменная окружения AGENT_CORE_URL (явный публичный URL core runtime).
        2. Конфигурация API_HOST/API_PORT (как в ApiModule).
        """
        env_url = os.getenv("AGENT_CORE_URL")
        if env_url:
            return env_url.rstrip("/")

        api_host = os.getenv("API_HOST", "0.0.0.0")
        api_port = int(os.getenv("API_PORT", "8000"))
        display_host = "127.0.0.1" if api_host == "0.0.0.0" else api_host
        return f"http://{display_host}:{api_port}"

    async def deploy(self, credential_id: str, agent_name: str) -> Dict[str, Any]:
        """
        Запустить SSH‑деплой агента на удалённом хосте.

        Flow:
        1. Получить SSH credential из CredentialRepository.
        2. Сгенерировать одноразовый enrollment token (TTL 10 минут).
        3. Через SSHExecutionService:
           - создать временную директорию;
           - загрузить installer script;
           - выполнить installer с параметрами: enrollment_token, core_url.
        4. Вернуть статус запуска деплоя.

        НЕ логирует enrollment token и секреты.
        """
        if not credential_id:
            raise ValueError("credential_id is required")
        if not agent_name or not agent_name.strip():
            raise ValueError("agent_name must be non-empty")

        agent_name = agent_name.strip()

        # Structured log: deploy_started
        await log_info(
            self._runtime,
            "[AgentDeploy] deploy_started",
            agent_name=agent_name,
            credential_id=credential_id,
        )

        # 1. Credential + secret
        credential = await self._get_credential_with_secret(credential_id)

        # 2. Enrollment token (одноразовый, TTL 10 минут)
        enrollment_token = await self._generate_enrollment_token(agent_name)
        core_url = self._compute_core_url()

        # 3. SSH: временная директория + upload + exec
        remote_dir = os.path.join(
            self._config.remote_base_dir,
            f"home-agent-{uuid.uuid4().hex[:8]}",
        )
        remote_script_path = os.path.join(remote_dir, "agent_install.sh")
        installer_path = self._resolve_installer_path()

        # 3.1 Создать временную директорию на удалённом хосте
        mkdir_cmd = f"mkdir -p {shlex.quote(remote_dir)}"
        mkdir_result = await self._ssh.run_command(credential, mkdir_cmd)
        if mkdir_result["exit_code"] != 0:
            await log_info(
                self._runtime,
                "[AgentDeploy] ssh_mkdir_failed",
                agent_name=agent_name,
                credential_id=credential_id,
                exit_code=mkdir_result["exit_code"],
            )
            raise RuntimeError(f"Failed to create remote directory: {remote_dir}")

        await log_info(
            self._runtime,
            "[AgentDeploy] ssh_connected",
            agent_name=agent_name,
            credential_id=credential_id,
            remote_dir=remote_dir,
        )

        # 3.2 Загрузить installer script
        await self._ssh.upload_file(credential, str(installer_path), remote_script_path)
        await log_info(
            self._runtime,
            "[AgentDeploy] installer_uploaded",
            agent_name=agent_name,
            credential_id=credential_id,
            remote_path=remote_script_path,
        )

        # 3.3 Сделать скрипт исполняемым
        chmod_cmd = f"chmod +x {shlex.quote(remote_script_path)}"
        chmod_result = await self._ssh.run_command(credential, chmod_cmd)
        if chmod_result["exit_code"] != 0:
            await log_info(
                self._runtime,
                "[AgentDeploy] installer_chmod_failed",
                agent_name=agent_name,
                credential_id=credential_id,
                exit_code=chmod_result["exit_code"],
            )
            raise RuntimeError("Failed to chmod installer script on remote host")

        # 3.4 Выполнить installer с безопасным quoting параметров
        safe_token = shlex.quote(enrollment_token)
        safe_core_url = shlex.quote(core_url)
        install_cmd = f"cd {shlex.quote(remote_dir)} && ./agent_install.sh {safe_token} {safe_core_url}"

        # ВАЖНО: не логируем команду целиком, чтобы не утечь token.
        install_result = await self._ssh.run_command(credential, install_cmd)

        await log_info(
            self._runtime,
            "[AgentDeploy] installer_executed",
            agent_name=agent_name,
            credential_id=credential_id,
            exit_code=install_result["exit_code"],
        )

        # BEST EFFORT: не ждём окончания bootstrap/heartbeat — только факт запуска.
        await log_info(
            self._runtime,
            "[AgentDeploy] deploy_finished",
            agent_name=agent_name,
            credential_id=credential_id,
            ssh_exit_code=install_result["exit_code"],
        )

        # Минимизируем время жизни токена в памяти
        enrollment_token = ""  # type: ignore[assignment]

        return {
            "status": "deploy_started",
            "agent_name": agent_name,
        }


async def admin_agent_deploy(runtime: Any, body: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Admin‑обёртка для HTTP endpoint:

    POST /admin/v1/agents/deploy
    Body:
        {
           "credential_id": "...",
           "agent_name": "..."
        }
    """
    if not isinstance(body, dict):
        raise ValueError("body is required and must be an object")

    credential_id = str(body.get("credential_id") or "").strip()
    agent_name = str(body.get("agent_name") or "").strip()

    if not credential_id:
        raise ValueError("credential_id is required")
    if not agent_name:
        raise ValueError("agent_name is required")

    service = AgentDeployService(runtime)
    result = await service.deploy(credential_id=credential_id, agent_name=agent_name)
    return result

