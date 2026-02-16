"""
ProcessExecutor — выполнение операций через subprocess.

Протокол:
stdin → JSON с operation параметрами
stdout ← JSON с результатом

Процесс должен читать из stdin, обрабатывать operation, писать в stdout.
"""

import json
import asyncio
import logging
import subprocess
from typing import Any, Optional, Dict

from core.operations import Operation

logger = logging.getLogger(__name__)


class ProcessExecutorError(Exception):
    """Error in process execution."""
    pass


class ProcessExecutor:
    """Execute operations in isolated subprocess."""
    
    # Default process configuration
    DEFAULT_TIMEOUT = 30  # seconds
    DEFAULT_MAX_RETRIES = 3
    
    def __init__(self, runtime: Any):
        """Initialize executor."""
        self.runtime = runtime
    
    async def execute(
        self,
        operation: Operation,
        config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Execute operation in subprocess.
        
        Args:
            operation: Operation to execute
            config: Process config {"cmd": "...", "timeout": 30, "max_retries": 3}
            
        Returns:
            Result dict
            
        Raises:
            ProcessExecutorError: if execution fails
        """
        config = config or {}
        
        # Get process command
        cmd = config.get("cmd")
        if not cmd:
            raise ProcessExecutorError("Process config missing 'cmd' field")
        
        timeout = config.get("timeout", self.DEFAULT_TIMEOUT)
        
        try:
            # Prepare payload
            payload = {
                "protocol_version": 1,
                "capability": operation.type,
                "operation_id": operation.operation_id,
                "params": operation.params or {}
            }
            
            # Execute subprocess
            result = await self._run_process(cmd, payload, timeout)
            
            return {
                "success": True,
                "result": result
            }
        
        except ProcessExecutorError:
            raise
        except Exception as e:
            logger.error(f"Process execution failed: {str(e)}")
            raise ProcessExecutorError(f"Process execution failed: {str(e)}")
    
    async def _run_process(
        self,
        cmd: str,
        payload: Dict[str, Any],
        timeout: float
    ) -> Dict[str, Any]:
        """
        Run process with payload.
        
        Args:
            cmd: Command to run (e.g., "python plugin/handler.py")
            payload: Input payload as dict
            timeout: Process timeout in seconds
            
        Returns:
            Process output as dict
            
        Raises:
            ProcessExecutorError: on error
        """
        import shlex
        
        try:
            # Parse command
            cmd_parts = shlex.split(cmd)
            
            # Prepare input as JSON
            input_data = json.dumps(payload).encode("utf-8")
            
            # Run process asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            # Execute with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(input=input_data),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                process.kill()
                raise ProcessExecutorError(f"Process timeout after {timeout}s")
            
            # Check exit code
            if process.returncode != 0:
                error_msg = stderr.decode("utf-8", errors="replace")
                raise ProcessExecutorError(f"Process failed: {error_msg}")
            
            # Parse output
            output_data = stdout.decode("utf-8")
            try:
                result = json.loads(output_data)
            except json.JSONDecodeError as e:
                raise ProcessExecutorError(f"Invalid JSON response: {str(e)}")
            
            # Validate response
            if not isinstance(result, dict):
                raise ProcessExecutorError("Response must be JSON object")
            
            if not result.get("success", False):
                error = result.get("error", "Unknown error")
                raise ProcessExecutorError(f"Process error: {error}")
            
            return result.get("result", {})
        
        except ProcessExecutorError:
            raise
        except Exception as e:
            raise ProcessExecutorError(f"Process execution error: {str(e)}")
