"""AgentDeployService — SSH bootstrap for agent deployment."""

from __future__ import annotations

import os
import shlex
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Tuple

from core.logger_helper import info as log_info

from modules.credentials import CredentialRepository
from modules.ssh.ssh_execution_service import SSHExecutionService

CredentialWithSecret = Tuple[Any, bytes]


@dataclass
class AgentDeployConfig:
    """Configuration for agent SSH deployment."""

    installer_relative_path: str = "installer_templates/agent_install.sh"
    remote_base_dir: str = "/tmp"


class AgentDeployService:
    """SSH deployment service for agents."""

    def __init__(self, runtime: Any, config: AgentDeployConfig | None = None) -> None:
        self._runtime = runtime
        self._config = config or AgentDeployConfig()
        self._ssh = SSHExecutionService()

    async def _get_credential_with_secret(
        self, credential_id: str
    ) -> CredentialWithSecret:
        storage_manager = getattr(self._runtime, "storage_manager", None)
        secret_store = getattr(self._runtime, "secret_store", None)
        if storage_manager is None or secret_store is None:
            raise ValueError(
                "Credential storage not configured (storage_manager or secret_store missing)"
            )

        repo = CredentialRepository(
            storage_manager=storage_manager, secret_store=secret_store
        )
        pair = await repo.get_with_secret(credential_id)
        if pair is None:
            raise ValueError(f"Credential {credential_id} not found")
        return pair

    async def _generate_enrollment_token(self, agent_name: str) -> str:
        agent_manager = getattr(self._runtime, "agent_manager", None)
        if agent_manager is None:
            raise ValueError(
                "AgentEnrollmentManager is not initialized on runtime (runtime.agent_manager)"
            )

        token = await agent_manager.generate_enrollment_token(agent_name)
        return token

    def _resolve_installer_path(self) -> Path:
        base_dir = Path(__file__).resolve().parent
        candidates = [
            base_dir / self._config.installer_relative_path,
            # Backward/forward compatibility: installer templates were moved under modules/agents.
            base_dir.parent / "agents" / "installer_templates" / "agent_install.sh",
        ]

        for installer_path in candidates:
            if installer_path.is_file():
                return installer_path

        searched = ", ".join(str(p) for p in candidates)
        raise FileNotFoundError(
            f"Agent installer script not found. Searched: {searched}"
        )

    def _compute_core_url(self) -> str:
        env_url = os.getenv("AGENT_CORE_URL")
        if env_url:
            return env_url.rstrip("/")

        api_host = os.getenv("API_HOST", "0.0.0.0")
        api_port = int(os.getenv("API_PORT", "8000"))

        if api_host and api_host != "0.0.0.0":
            return f"http://{api_host}:{api_port}"

        lan_ip = self._get_lan_ip()
        return f"http://{lan_ip}:{api_port}"

    @staticmethod
    def _get_lan_ip() -> str:
        import socket

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"

    async def deploy(
        self,
        credential_id: str,
        agent_name: str,
        core_url: str | None = None,
    ) -> Dict[str, Any]:
        if not credential_id:
            raise ValueError("credential_id is required")
        if not agent_name or not agent_name.strip():
            raise ValueError("agent_name must be non-empty")

        agent_name = agent_name.strip()

        await log_info(
            self._runtime,
            "[AgentDeploy] deploy_started",
            agent_name=agent_name,
            credential_id=credential_id,
        )

        credential = await self._get_credential_with_secret(credential_id)

        enrollment_token = await self._generate_enrollment_token(agent_name)
        core_url = (core_url or "").strip().rstrip("/") or self._compute_core_url()

        remote_dir = os.path.join(
            self._config.remote_base_dir,
            f"home-agent-{uuid.uuid4().hex[:8]}",
        )
        remote_script_path = os.path.join(remote_dir, "agent_install.sh")
        installer_path = self._resolve_installer_path()

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

        await self._ssh.upload_file(credential, str(installer_path), remote_script_path)
        await log_info(
            self._runtime,
            "[AgentDeploy] installer_uploaded",
            agent_name=agent_name,
            credential_id=credential_id,
            remote_path=remote_script_path,
        )

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

        safe_token = shlex.quote(enrollment_token)
        safe_core_url = shlex.quote(core_url)
        install_cmd = f"cd {shlex.quote(remote_dir)} && ./agent_install.sh {safe_token} {safe_core_url}"

        install_result = await self._ssh.run_command(
            credential, install_cmd, timeout=300
        )

        await log_info(
            self._runtime,
            "[AgentDeploy] installer_executed",
            agent_name=agent_name,
            credential_id=credential_id,
            exit_code=install_result["exit_code"],
        )

        await log_info(
            self._runtime,
            "[AgentDeploy] deploy_finished",
            agent_name=agent_name,
            credential_id=credential_id,
            ssh_exit_code=install_result["exit_code"],
        )

        enrollment_token = ""  # type: ignore[assignment]

        return {
            "status": "deploy_started",
            "agent_name": agent_name,
            "install_exit_code": install_result["exit_code"],
            "install_stdout": install_result.get("stdout", ""),
            "install_stderr": install_result.get("stderr", ""),
        }


__all__ = ["AgentDeployConfig", "AgentDeployService"]
