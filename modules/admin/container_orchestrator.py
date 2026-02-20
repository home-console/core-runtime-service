"""
ContainerOrchestrator — управление жизненным циклом контейнеров плагинов.

Архитектурное разделение:
- Runtime знает только о существующих контейнерах (restart)
- ContainerOrchestrator знает о сборке и создании контейнеров
- Вся информация берётся из plugin.metadata.container_config

Правила:
- Не знает конкретные плагины (работает через metadata)
- Не содержит хардкодов имён образов или путей
- Использует только информацию из container_config
"""

import asyncio
import logging
import shutil
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class ContainerOrchestrator:
    """
    Управление жизненным циклом контейнеров плагинов.
    
    Отвечает за:
    - Проверку существования контейнера
    - Сборку образа (если указано в metadata)
    - Создание и запуск контейнера (если указано в metadata)
    """
    
    def __init__(self, project_root: Optional[Path] = None):
        """
        Инициализация ContainerOrchestrator.
        
        Args:
            project_root: корень проекта (для сборки образов). 
                         Если None, будет определён автоматически.
        """
        self._project_root = project_root
        self._docker_cmd = shutil.which("docker")
        if not self._docker_cmd:
            logger.warning("Docker not found in PATH")
    
    def _find_project_root(self) -> Optional[Path]:
        """Найти корень проекта (где есть deployment/ или core-runtime-service/)."""
        if self._project_root:
            return self._project_root
        
        possible_roots = [
            Path("/app"),
            Path.cwd(),
            Path(__file__).parent.parent.parent.parent,  # от modules/admin/ до корня
        ]
        
        for root in possible_roots:
            if (root / "deployment" / "docker-compose.yml").exists():
                return root
            if (root / "core-runtime-service").exists():
                return root
        
        return None
    
    async def container_exists(self, container_name: str) -> bool:
        """
        Проверить существование контейнера.
        
        Args:
            container_name: имя контейнера
            
        Returns:
            True если контейнер существует
        """
        if not self._docker_cmd:
            return False
        
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_cmd,
                "ps",
                "-a",
                "--filter",
                f"name=^{container_name}$",
                "--format",
                "{{.Names}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            found_name = stdout.decode("utf-8", errors="replace").strip()
            return found_name == container_name
        except Exception as e:
            logger.warning(f"Error checking container existence: {e}")
            return False
    
    async def remove_container(self, container_name: str, force: bool = False) -> Dict[str, Any]:
        """
        Удалить контейнер.
        
        Args:
            container_name: имя контейнера
            force: если True, использует --force для остановки перед удалением
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        if not self._docker_cmd:
            return {"ok": False, "error": "Docker не найден в системе"}
        
        cmd = [self._docker_cmd, "rm"]
        if force:
            cmd.append("--force")
        cmd.append(container_name)
        
        try:
            logger.info(f"Removing container {container_name} (force={force})")
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)
            
            if proc.returncode == 0:
                logger.info(f"Container {container_name} removed successfully")
                return {"ok": True, "message": f"Контейнер '{container_name}' успешно удалён"}
            else:
                error_msg = stderr.decode("utf-8", errors="replace") if stderr else "Неизвестная ошибка"
                logger.warning(f"Failed to remove container {container_name}: {error_msg}")
                return {"ok": False, "error": f"Не удалось удалить контейнер: {error_msg}"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Таймаут при удалении контейнера"}
        except Exception as e:
            logger.exception(f"Error removing container {container_name}")
            return {"ok": False, "error": f"Ошибка при удалении контейнера: {str(e)}"}
    
    async def image_exists(self, image_name: str) -> bool:
        """
        Проверить существование образа.
        
        Args:
            image_name: имя образа
            
        Returns:
            True если образ существует
        """
        if not self._docker_cmd:
            return False
        
        try:
            proc = await asyncio.create_subprocess_exec(
                self._docker_cmd,
                "images",
                "-q",
                image_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10.0)
            return bool(stdout.decode("utf-8", errors="replace").strip())
        except Exception as e:
            logger.warning(f"Error checking image existence: {e}")
            return False
    
    async def build_image(
        self,
        image_name: str,
        dockerfile_path: str,
        build_context: str,
    ) -> Dict[str, Any]:
        """
        Собрать Docker образ.
        
        Args:
            image_name: имя образа для сборки
            dockerfile_path: путь к Dockerfile (относительно build_context)
            build_context: путь к build context
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        if not self._docker_cmd:
            return {"ok": False, "error": "Docker не найден в системе"}
        
        # Проверяем, что Dockerfile существует и получаем его абсолютный путь
        dockerfile_full = (
            Path(build_context) / dockerfile_path
            if not Path(dockerfile_path).is_absolute()
            else Path(dockerfile_path)
        )
        if not dockerfile_full.exists():
            # Пробуем также относительно project_root (на случай, если context относительный)
            project_root = self._find_project_root()
            if project_root:
                candidate = (
                    project_root / dockerfile_path
                    if not Path(dockerfile_path).is_absolute()
                    else Path(dockerfile_path)
                )
                if candidate.exists():
                    dockerfile_full = candidate
                else:
                    return {
                        "ok": False,
                        "error": f"Dockerfile не найден: {dockerfile_full} (также проверен: {candidate})",
                    }
            else:
                return {
                    "ok": False,
                    "error": f"Dockerfile не найден: {dockerfile_full}",
                }

        # Используем абсолютный путь к Dockerfile, чтобы не зависеть от cwd процесса
        build_cmd = [
            self._docker_cmd,
            "build",
            "-t",
            image_name,
            "-f",
            str(dockerfile_full),
            build_context,
        ]
        
        try:
            logger.info(f"Building image {image_name} from {dockerfile_path} (context: {build_context})")
            proc = await asyncio.create_subprocess_exec(
                *build_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=600.0)  # 10 минут
            
            if proc.returncode == 0:
                logger.info(f"Image {image_name} built successfully")
                return {"ok": True, "message": f"Образ {image_name} успешно собран"}
            else:
                error_msg = stderr.decode("utf-8", errors="replace") if stderr else "Неизвестная ошибка"
                logger.error(f"Failed to build image {image_name}: {error_msg}")
                return {"ok": False, "error": f"Не удалось собрать образ: {error_msg}"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Таймаут при сборке образа (более 10 минут)"}
        except Exception as e:
            logger.exception(f"Error building image {image_name}")
            return {"ok": False, "error": f"Ошибка при сборке образа: {str(e)}"}
    
    async def create_container(
        self,
        container_name: str,
        image_name: str,
        container_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Создать и запустить контейнер.
        
        Args:
            container_name: имя контейнера
            image_name: имя образа
            container_config: конфигурация контейнера из metadata.container_config
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        if not self._docker_cmd:
            return {"ok": False, "error": "Docker не найден в системе"}
        
        run_cmd = [self._docker_cmd, "run", "-d", "--name", container_name]

        # Опциональная сеть контейнера
        network = container_config.get("network")
        if isinstance(network, str) and network.strip():
            network = network.strip()
            try:
                # Проверяем, существует ли сеть
                inspect_proc = await asyncio.create_subprocess_exec(
                    self._docker_cmd,
                    "network",
                    "inspect",
                    network,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, inspect_stderr = await asyncio.wait_for(inspect_proc.communicate(), timeout=10.0)

                if inspect_proc.returncode != 0:
                    # Пытаемся создать сеть
                    logger.info(f"Network {network} not found, creating it")
                    create_net_proc = await asyncio.create_subprocess_exec(
                        self._docker_cmd,
                        "network",
                        "create",
                        network,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    _, create_net_stderr = await asyncio.wait_for(create_net_proc.communicate(), timeout=30.0)
                    if create_net_proc.returncode != 0:
                        error_msg = create_net_stderr.decode("utf-8", errors="replace") if create_net_stderr else "Неизвестная ошибка"
                        logger.warning(f"Failed to create network {network}: {error_msg}")
                        return {"ok": False, "error": f"Не удалось создать сеть Docker '{network}': {error_msg}"}

                # Добавляем сеть к команде запуска
                run_cmd.extend(["--network", network])
            except asyncio.TimeoutError:
                return {"ok": False, "error": f"Таймаут при проверке/создании сети Docker '{network}'"}
            except Exception as e:
                logger.exception(f"Error ensuring docker network {network}")
                return {"ok": False, "error": f"Ошибка при настройке сети Docker '{network}': {str(e)}"}
        
        # Добавляем аргументы из container_config
        if isinstance(container_config.get("args"), list):
            run_cmd.extend(container_config["args"])
        
        # Добавляем порты
        if isinstance(container_config.get("ports"), dict):
            for host_port, container_port in container_config["ports"].items():
                run_cmd.extend(["-p", f"{host_port}:{container_port}"])
        
        # Добавляем переменные окружения
        if isinstance(container_config.get("env"), dict):
            for key, value in container_config["env"].items():
                run_cmd.extend(["-e", f"{key}={value}"])
        
        # Добавляем volumes
        if isinstance(container_config.get("volumes"), list):
            for volume in container_config["volumes"]:
                run_cmd.extend(["-v", volume])
        
        # Добавляем image
        run_cmd.append(image_name)
        
        # Добавляем команду запуска
        if isinstance(container_config.get("cmd"), list):
            run_cmd.extend(container_config["cmd"])
        
        try:
            logger.info(f"Creating container {container_name} with command: {' '.join(run_cmd)}")
            proc = await asyncio.create_subprocess_exec(
                *run_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120.0)
            
            if proc.returncode == 0:
                container_id = stdout.decode("utf-8", errors="replace").strip()
                logger.info(f"Container {container_name} created successfully with ID: {container_id}")
                return {
                    "ok": True,
                    "message": f"Контейнер '{container_name}' успешно создан и запущен"
                }
            else:
                error_msg = stderr.decode("utf-8", errors="replace") if stderr else "Неизвестная ошибка"
                logger.error(f"Failed to create container {container_name}: {error_msg}")
                return {"ok": False, "error": f"Не удалось создать контейнер: {error_msg}"}
        except asyncio.TimeoutError:
            return {"ok": False, "error": "Таймаут при создании контейнера"}
        except Exception as e:
            logger.exception(f"Error creating container {container_name}")
            return {"ok": False, "error": f"Ошибка при создании контейнера: {str(e)}"}
    
    async def ensure_container(
        self,
        container_name: str,
        container_config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Убедиться, что контейнер существует и запущен.
        
        Если контейнер не существует:
        1. Проверяет наличие образа
        2. Если образа нет и указан build в container_config — собирает образ
        3. Создаёт и запускает контейнер
        
        Args:
            container_name: имя контейнера
            container_config: конфигурация из plugin.metadata.container_config
            
        Returns:
            {"ok": True} при успехе, {"ok": False, "error": "..."} при ошибке
        """
        if not self._docker_cmd:
            return {"ok": False, "error": "Docker не найден в системе"}
        
        # Проверяем существование контейнера
        if await self.container_exists(container_name):
            logger.info(f"Container {container_name} already exists")
            return {"ok": True, "message": f"Контейнер '{container_name}' уже существует"}
        
        # Получаем имя образа
        image_name = container_config.get("image")
        if not image_name:
            return {
                "ok": False,
                "error": "Не указан 'image' в container_config. Невозможно создать контейнер."
            }
        
        # Проверяем существование образа
        image_exists = await self.image_exists(image_name)
        
        # Если образа нет, пытаемся собрать
        if not image_exists:
            build_config = container_config.get("build")
            if build_config and build_config.get("auto_build", False):
                project_root = self._find_project_root()
                if not project_root:
                    return {
                        "ok": False,
                        "error": "Не удалось определить корень проекта для сборки образа"
                    }
                
                dockerfile_path = build_config.get("dockerfile")
                build_context_rel = build_config.get("context", ".")
                
                if not dockerfile_path:
                    return {
                        "ok": False,
                        "error": "Не указан 'dockerfile' в container_config.build"
                    }
                
                # Build context относительно корня проекта
                build_context = str(project_root / build_context_rel)
                
                build_result = await self.build_image(image_name, dockerfile_path, build_context)
                if not build_result["ok"]:
                    return build_result
            else:
                return {
                    "ok": False,
                    "error": f"Образ '{image_name}' не найден и автоматическая сборка отключена. "
                            f"Установите 'build.auto_build: true' в container_config для автоматической сборки."
                }
        
        # Создаём контейнер
        return await self.create_container(container_name, image_name, container_config)
