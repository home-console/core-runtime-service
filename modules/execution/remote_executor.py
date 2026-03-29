"""
RemoteOperationExecutor - выполняет операции через HTTP к remote capability providers.

Module-owned remote execution logic:
- Protocol versioning и negotiation
- Manifest discovery
- Health monitoring
- Retryable error handling
- Per-capability timeouts
"""

from typing import Any, Dict, Optional

from core.capability import protocol as capability_protocol
from core.operations.remote_executor_interface import IRemoteExecutor


class RemoteOperationExecutor(IRemoteExecutor):
    """
    Executor для remote capability operations.

    Поддерживает Capability Protocol v1:
    - request header: X-HomeConsole-Protocol: 1
    - request body: protocol_version, capability, operation_id, params, context
    - validates response protocol_version
    - handles retryable errors
    """

    @staticmethod
    async def execute_remote(
        base_url: str,
        capability: str,
        operation_id: str,
        params: Dict[str, Any],
        context: Dict[str, Any],
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            import httpx
        except ImportError:
            raise RuntimeError(
                "httpx is required for remote capability execution. Install: pip install httpx"
            )

        if timeout is None:
            timeout = capability_protocol.DEFAULT_CAPABILITY_TIMEOUT

        endpoint_url = f"{base_url.rstrip('/')}/capability/execute"
        payload: capability_protocol.CapabilityExecuteRequest = {
            "protocol_version": capability_protocol.PROTOCOL_VERSION,
            "capability": capability,
            "operation_id": operation_id,
            "params": params,
            "context": context or {},
        }

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    endpoint_url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        capability_protocol.PROTOCOL_HEADER: str(
                            capability_protocol.PROTOCOL_VERSION
                        ),
                    },
                )

                if response.status_code >= 400:
                    error_text = response.text[:500]
                    raise RuntimeError(
                        f"Remote provider HTTP {response.status_code}: {error_text}"
                    )

                response_data = response.json()

                if not isinstance(response_data, dict):
                    raise ValueError("Remote provider returned invalid response: not a dict")

                status = response_data.get("status")
                if status not in ("success", "error"):
                    raise ValueError(f"Remote provider returned invalid status: {status}")

                capability_protocol.check_protocol_compatibility(response_data)
                return response_data

        except httpx.TimeoutException as e:
            raise RuntimeError(
                f"Remote provider request timeout ({timeout}s): {endpoint_url}"
            ) from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise RuntimeError(f"Cannot connect to remote provider: {endpoint_url}") from e
        except capability_protocol.ProtocolCompatibilityError:
            raise
        except Exception as e:
            raise RuntimeError(f"Remote operation execution failed: {e}") from e

    @staticmethod
    async def get_manifest(
        base_url: str,
        timeout: Optional[float] = None,
    ) -> Optional[capability_protocol.CapabilityManifest]:
        try:
            import httpx
        except ImportError:
            return None

        if timeout is None:
            timeout = capability_protocol.DEFAULT_MANIFEST_TIMEOUT

        endpoint_url = f"{base_url.rstrip('/')}/capability/manifest"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    endpoint_url,
                    headers={
                        capability_protocol.PROTOCOL_HEADER: str(
                            capability_protocol.PROTOCOL_VERSION
                        ),
                    },
                )

                if response.status_code == 404:
                    return None
                if response.status_code >= 400:
                    return None

                manifest = response.json()
                if not isinstance(manifest, dict):
                    return None
                if "protocol_version" not in manifest or "provider_version" not in manifest:
                    return None

                capability_protocol.check_protocol_compatibility(manifest)
                return manifest

        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
            return None
        except Exception:
            return None

    @staticmethod
    async def check_health(
        base_url: str,
        timeout: Optional[float] = None,
    ) -> Optional[capability_protocol.CapabilityHealth]:
        try:
            import httpx
        except ImportError:
            return None

        if timeout is None:
            timeout = capability_protocol.DEFAULT_HEALTH_CHECK_TIMEOUT

        endpoint_url = f"{base_url.rstrip('/')}/capability/health"

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    endpoint_url,
                    headers={
                        capability_protocol.PROTOCOL_HEADER: str(
                            capability_protocol.PROTOCOL_VERSION
                        ),
                    },
                )

                if response.status_code == 404:
                    return None
                if response.status_code >= 400:
                    return None

                health = response.json()
                if not isinstance(health, dict):
                    return None
                return health

        except (httpx.TimeoutException, httpx.ConnectError, httpx.NetworkError):
            return None
        except Exception:
            return None

    @staticmethod
    def is_remote_response_success(response: Dict[str, Any]) -> bool:
        return response.get("status") == "success"

    @staticmethod
    def is_error_retryable(response: Dict[str, Any]) -> bool:
        if response.get("status") != "error":
            return False

        error = response.get("error", {})
        if isinstance(error, dict):
            retryable = error.get("retryable")
            if retryable is not None:
                return bool(retryable)

            code = error.get("code", "")
            return capability_protocol.is_retryable_error(str(code))

        return False

    @staticmethod
    def extract_result(response: Dict[str, Any]) -> Any:
        if response.get("status") == "success":
            return response.get("result")

        error = response.get("error", {})
        raise RuntimeError(f"Remote error: {error.get('message', 'Unknown error')}")
