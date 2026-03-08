"""
SSHExecutionService — безопасное выполнение команд и загрузка файлов по SSH.

Использует paramiko.SSHClient и exec_command (без invoke_shell).
Не логирует секреты и не хранит их дольше, чем нужно для подключения.
"""

from __future__ import annotations

from typing import Any, Dict, Tuple
import io
import asyncio

import paramiko  # type: ignore[import-not-found]

from core.credentials.domain import Credential, CredentialType


CredentialWithSecret = Tuple[Credential, bytes]


class SSHExecutionService:
    """
    Высокоуровневый сервис для работы по SSH.

    Ожидает credential в виде (Credential, secret_bytes), полученного из CredentialRepository.get_with_secret().
    """

    def __init__(self, *, timeout: int = 30) -> None:
        self._timeout = timeout

    def _normalize_credential(self, credential: Any) -> CredentialWithSecret:
        """
        Привести credential к паре (Credential, secret_bytes).

        Секрет не логируется и используется только для установления соединения.
        """
        if (
            isinstance(credential, tuple)
            and len(credential) == 2
            and isinstance(credential[0], Credential)
            and isinstance(credential[1], (bytes, bytearray))
        ):
            cred_obj: Credential = credential[0]
            secret_bytes: bytes = bytes(credential[1])
            return cred_obj, secret_bytes

        raise ValueError("SSHExecutionService expects credential as (Credential, secret_bytes) tuple")

    def _connect(self, cred: Credential, secret_bytes: bytes) -> paramiko.SSHClient:
        """
        Синхронное установление SSH-подключения.

        Не логирует и не возвращает секрет.
        """
        if cred.type not in (CredentialType.SSH_PASSWORD, CredentialType.SSH_KEY):
            raise ValueError(f"Unsupported credential type for SSH: {cred.type}")
        if not cred.host or not cred.username:
            raise ValueError("Credential must contain host and username for SSH connection")

        host = cred.host
        port = cred.port or 22
        username = cred.username
        secret_str = secret_bytes.decode("utf-8", errors="replace").strip()

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            if cred.type == CredentialType.SSH_PASSWORD:
                client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    password=secret_str,
                    timeout=self._timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
            else:
                # SSH_KEY
                pkey = None
                for key_cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
                    try:
                        pkey = key_cls.from_private_key(io.StringIO(secret_str))
                        break
                    except Exception:
                        continue
                if pkey is None:
                    raise ValueError("Unsupported private key format (RSA/Ed25519/ECDSA required)")

                client.connect(
                    hostname=host,
                    port=port,
                    username=username,
                    pkey=pkey,
                    timeout=self._timeout,
                    allow_agent=False,
                    look_for_keys=False,
                )
            return client
        except Exception:
            # В случае ошибки обязательно закрываем клиент
            try:
                client.close()
            except Exception:
                pass
            raise
        finally:
            # Локальная строка с секретом больше не нужна
            secret_str = ""  # type: ignore[assignment]

    def _upload_file_sync(
        self,
        credential: CredentialWithSecret,
        local_path: str,
        remote_path: str,
    ) -> None:
        cred, secret_bytes = credential
        client = self._connect(cred, secret_bytes)
        try:
            sftp = client.open_sftp()
            try:
                sftp.put(local_path, remote_path)
            finally:
                sftp.close()
        finally:
            try:
                client.close()
            except Exception:
                pass

    def _run_command_sync(
        self,
        credential: CredentialWithSecret,
        command: str,
        timeout: int | None = None,
    ) -> Dict[str, Any]:
        cred, secret_bytes = credential
        client = self._connect(cred, secret_bytes)
        effective_timeout = timeout if timeout is not None else self._timeout
        try:
            stdin, stdout, stderr = client.exec_command(command, timeout=effective_timeout)

            out_bytes = stdout.read()
            err_bytes = stderr.read()
            exit_status = stdout.channel.recv_exit_status()

            stdout_text = out_bytes.decode("utf-8", errors="replace") if out_bytes else ""
            stderr_text = err_bytes.decode("utf-8", errors="replace") if err_bytes else ""

            return {
                "exit_code": int(exit_status),
                "stdout": stdout_text,
                "stderr": stderr_text,
            }
        finally:
            try:
                client.close()
            except Exception:
                pass

    async def upload_file(self, credential: Any, local_path: str, remote_path: str) -> None:
        """
        Загрузить локальный файл на удалённый хост по SSH.

        credential — (Credential, secret_bytes) из CredentialRepository.get_with_secret().
        """
        cred_pair = self._normalize_credential(credential)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._upload_file_sync, cred_pair, local_path, remote_path)

    async def run_command(self, credential: Any, command: str, timeout: int | None = None) -> Dict[str, Any]:
        """
        Выполнить команду на удалённом хосте по SSH через exec_command.

        Args:
            timeout: override channel timeout in seconds (uses instance default if None)

        Возвращает:
            {
                "exit_code": int,
                "stdout": str,
                "stderr": str,
            }
        """
        cred_pair = self._normalize_credential(credential)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, self._run_command_sync, cred_pair, command, timeout
        )

