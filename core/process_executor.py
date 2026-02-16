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
import os
import signal
from typing import Any, Optional, Dict

from core.operations import Operation

logger = logging.getLogger(__name__)


class ProcessExecutorError(Exception):
    """Error in process execution."""
    pass


class StreamLimitExceededError(ProcessExecutorError):
    """Stream output exceeded maximum size limit."""
    pass


async def _read_stream_with_limit(stream, max_size: int, stream_name: str):
    """
    Async generator to read stream with size limit.
    
    Chunks are yielded as they're read. If total > max_size, raises StreamLimitExceededError.
    """
    total_read = 0
    chunk_size = 8192  # 8KB chunks
    
    while True:
        chunk = await stream.read(chunk_size)
        if not chunk:
            break
        
        total_read += len(chunk)
        if total_read > max_size:
            raise StreamLimitExceededError(
                f"Process {stream_name} exceeded {max_size} bytes limit "
                f"(read {total_read} bytes)"
            )
        
        yield chunk


class ProcessExecutor:
    """Execute operations in isolated subprocess."""
    
    # Default process configuration
    DEFAULT_TIMEOUT = 30  # seconds
    DEFAULT_MAX_RETRIES = 3
    
    # P0 Hardening: Maximum output size (50MB)
    MAX_OUTPUT_SIZE = 50 * 1024 * 1024  # 50MB
    
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
        Run process with payload using streaming stdout read (P0: memory safe).
        
        Args:
            cmd: Command to run (e.g., "python plugin/handler.py")
            payload: Input payload as dict
            timeout: Process timeout in seconds
            
        Returns:
            Process output as dict
            
        Raises:
            ProcessExecutorError: on error (including MAX_OUTPUT_SIZE exceeded)
        """
        import shlex
        
        try:
            # Parse command
            cmd_parts = shlex.split(cmd)
            
            # Prepare input as JSON
            input_data = json.dumps(payload).encode("utf-8")
            
            # P0: Run process with process group (for cleanup)
            # On Unix systems, preexec_fn=os.setsid creates a new process group
            preexec_fn = None
            if os.name != 'nt':  # Not Windows
                preexec_fn = os.setsid
            
            # Run process asynchronously
            process = await asyncio.create_subprocess_exec(
                *cmd_parts,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                preexec_fn=preexec_fn
            )
            
            try:
                # P0: Stream stdout reading instead of communicate() to enforce MAX_OUTPUT_SIZE
                stdout_data = b""
                stderr_data = b""
                
                # Send input to process
                process.stdin.write(input_data)
                await process.stdin.drain()
                process.stdin.close()
                
                # Read stdout with size limit
                try:
                    async for chunk in _read_stream_with_limit(
                        process.stdout,
                        self.MAX_OUTPUT_SIZE,
                        "stdout"
                    ):
                        stdout_data += chunk
                except StreamLimitExceededError as e:
                    # Kill process - it's outputting too much
                    try:
                        if os.name != 'nt':
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        else:
                            process.kill()
                    except Exception:
                        pass
                    raise ProcessExecutorError(str(e))
                
                # Read stderr (with size limit too)
                try:
                    async for chunk in _read_stream_with_limit(
                        process.stderr,
                        self.MAX_OUTPUT_SIZE,
                        "stderr"
                    ):
                        stderr_data += chunk
                except StreamLimitExceededError as e:
                    try:
                        if os.name != 'nt':
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        else:
                            process.kill()
                    except Exception:
                        pass
                    raise ProcessExecutorError(str(e))
                
                # Wait for process with timeout
                try:
                    await asyncio.wait_for(
                        process.wait(),
                        timeout=timeout
                    )
                except asyncio.TimeoutError:
                    # Kill process group on timeout
                    try:
                        if os.name != 'nt':  # Unix
                            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                        else:  # Windows
                            process.kill()
                    except Exception as e:
                        logger.warning(f"Failed to kill process group: {e}")
                    
                    raise ProcessExecutorError(f"Process timeout after {timeout}s")
                
            except ProcessExecutorError:
                raise
            except Exception as e:
                # Cleanup on error
                try:
                    if os.name != 'nt':
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    else:
                        process.kill()
                except Exception:
                    pass
                raise ProcessExecutorError(f"Process communication error: {str(e)}")
            
            # Check exit code
            if process.returncode != 0:
                error_msg = stderr_data.decode("utf-8", errors="replace")
                raise ProcessExecutorError(f"Process failed: {error_msg}")
            
            # Parse output with proper error handling
            output_data = stdout_data.decode("utf-8")
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
