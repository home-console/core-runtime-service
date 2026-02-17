"""
ContainerExecutor — выполнение операций в docker/podman контейнере.

Протокол:
- Запускает docker run с образом
- Передает payload через stdin
- Читает результат из stdout
- Автоматически удаляет контейнер (--rm)

Кофиг:
{
  "image": "...",     # Docker image
  "timeout": 30,      # Container timeout
  "env": {...},       # Environment variables
  "volumes": {...},   # Volume mounts
  "resource_limits": {"memory": "256M", "cpus": "0.5"}
}
"""

import json
import asyncio
import logging
import subprocess
import shutil
import uuid
from typing import Any, Optional, Dict

from core.operations import Operation

logger = logging.getLogger(__name__)


class ContainerExecutorError(Exception):
    """Error in container execution."""
    pass


class ContainerExecutor:
    """Execute operations in isolated docker/podman container."""
    
    DEFAULT_TIMEOUT = 30  # seconds
    DEFAULT_IMAGE = None  # No default, must be specified
    
    def __init__(self, runtime: Any):
        """Initialize executor."""
        self.runtime = runtime
        self._docker_cmd = self._detect_docker()
    
    def _detect_docker(self) -> str:
        """Detect docker or podman availability."""
        import shutil
        
        if shutil.which("docker"):
            return "docker"
        elif shutil.which("podman"):
            return "podman"
        else:
            logger.warning("Neither docker nor podman found")
            return "docker"  # Default, will fail at runtime if not available
    
    async def execute(
        self,
        operation: Operation,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute operation in container.
        
        Args:
            operation: Operation to execute
            config: Container config {
                "image": "...",
                "timeout": 30,
                "env": {...},
                "volumes": {...},
                "resource_limits": {"memory": "256M"}
            }
            
        Returns:
            Result dict
            
        Raises:
            ContainerExecutorError: if execution fails
        """
        config = config or {}
        
        # P0: Check docker runtime is available before execution
        if not shutil.which(self._docker_cmd):
            raise ContainerExecutorError(f"Container runtime '{self._docker_cmd}' not available")
        
        # Get container image
        image = config.get("image")
        if not image:
            raise ContainerExecutorError("Container config missing 'image' field")
        
        timeout = config.get("timeout", self.DEFAULT_TIMEOUT)
        
        try:
            # Prepare payload
            payload = {
                "protocol_version": 1,
                "capability": operation.type,
                "operation_id": operation.operation_id,
                "params": operation.params or {}
            }
            
            # Execute container
            result = await self._run_container(image, payload, config, timeout)
            
            return {
                "success": True,
                "result": result
            }
        
        except ContainerExecutorError:
            raise
        except Exception as e:
            logger.error(f"Container execution failed: {str(e)}")
            raise ContainerExecutorError(f"Container execution failed: {str(e)}")
        
        try:
            # Prepare payload
            payload = {
                "protocol_version": 1,
                "capability": operation.type,
                "operation_id": operation.operation_id,
                "params": operation.params or {}
            }
            
            # Execute container
            result = await self._run_container(image, payload, config, timeout)
            
            return {
                "success": True,
                "result": result
            }
        
        except ContainerExecutorError:
            raise
        except Exception as e:
            logger.error(f"Container execution failed: {str(e)}")
            raise ContainerExecutorError(f"Container execution failed: {str(e)}")
    
    async def _run_container(
        self,
        image: str,
        payload: Dict[str, Any],
        config: Dict[str, Any],
        timeout: float
    ) -> Dict[str, Any]:
        """
        Run container with payload.
        
        Args:
            image: Docker image name
            payload: Input payload as dict
            config: Container configuration
            timeout: Container timeout in seconds
            
        Returns:
            Container output as dict
            
        Raises:
            ContainerExecutorError: on error
        """
        # P0: Generate unique container name for tracking
        container_name = f"hc_exec_{uuid.uuid4().hex[:12]}"
        
        try:
            # Build docker command
            cmd = [self._docker_cmd, "run", "--rm"]
            
            # P0: Add unique container name for tracking
            cmd.extend(["--name", container_name])
            
            # Add environment variables
            env = config.get("env", {})
            for key, value in env.items():
                cmd.extend(["-e", f"{key}={value}"])
            
            # Add volume mounts
            volumes = config.get("volumes", {})
            for host_path, container_path in volumes.items():
                cmd.extend(["-v", f"{host_path}:{container_path}"])
            
            # Add resource limits
            resource_limits = config.get("resource_limits", {})
            if "memory" in resource_limits:
                cmd.extend(["-m", resource_limits["memory"]])
            if "cpus" in resource_limits:
                cmd.extend(["--cpus", resource_limits["cpus"]])
            
            # Add image name
            cmd.append(image)
            
            # Prepare input as JSON
            input_data = json.dumps(payload).encode("utf-8")
            
            logger.info(f"Running container: {container_name}")
            
            # Run container asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            try:
                # Execute with timeout
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                raise ContainerExecutorError(f"Container timeout after {timeout}s")
            
            # Check exit code
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                raise ContainerExecutorError(f"Container failed: {error_msg}")
            
            # Parse output
            output_data = stdout.decode("utf-8")
            try:
                result = json.loads(output_data)
            except json.JSONDecodeError as e:
                raise ContainerExecutorError(f"Invalid JSON response: {str(e)}")
            
            # Validate response
            if not isinstance(result, dict):
                raise ContainerExecutorError("Response must be JSON object")
            
            if not result.get("success", False):
                error = result.get("error", "Unknown error")
                raise ContainerExecutorError(f"Container error: {error}")
            
            return result.get("result", {})
        
        except ContainerExecutorError:
            raise
        except Exception as e:
            raise ContainerExecutorError(f"Container execution error: {str(e)}")
        finally:
            # P0: Guaranteed cleanup — kill container even if docker daemon crashed
            try:
                cleanup_cmd = [self._docker_cmd, "rm", "-f", container_name]
                cleanup_process = await asyncio.create_subprocess_exec(
                    *cleanup_cmd,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL
                )
                await asyncio.wait_for(cleanup_process.wait(), timeout=5.0)
            except Exception as e:
                logger.warning(f"Failed to cleanup container {container_name}: {e}")
