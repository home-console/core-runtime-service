"""
Прокси-класс для управления remote plugins из Core Runtime.

Позволяет загружать и управлять удалёнными сервисами через HTTP контракт,
не изменяя Core Runtime.

Используется в тестах и демо.
"""

import asyncio
import json
import urllib.request
import urllib.error
from typing import Any, Optional

from .base_plugin import BasePlugin, PluginMetadata


class RemotePluginProxy(BasePlugin):
	"""Локальный прокси для удалённого плагина.
    
	Взаимодействует с удалённым плагином через HTTP, но представляется Core
	как обычный плагин через наследование от BasePlugin.
	"""

	def __init__(self, runtime: Any, remote_url: str):
		"""Инициализация прокси.
        
		Args:
			runtime: экземпляр CoreRuntime
			remote_url: базовый URL удалённого плагина (например, http://127.0.0.1:8001)
		"""
		super().__init__(runtime)
		self.remote_url = remote_url
		self._metadata: Optional[dict] = None
		# Список сервисов, зарегистрированных через proxy
		self._registered_services: list[str] = []
		# Таймаут для сетевых вызовов (секунды) — защищает от долгих блокировок
		self._http_timeout = 3

	async def _http_call(self, endpoint: str, method: str = "GET", json_data: Optional[dict] = None) -> dict:
		"""Вспомогательный метод для HTTP вызова через urllib."""
		url = f"{self.remote_url}{endpoint}"
		try:
			if method == "GET":
				with urllib.request.urlopen(url, timeout=self._http_timeout) as resp:
					return json.loads(resp.read().decode())
			elif method == "POST":
				req = urllib.request.Request(
					url,
					data=json.dumps(json_data or {}).encode(),
					headers={"Content-Type": "application/json"},
					method="POST",
				)
				with urllib.request.urlopen(req, timeout=self._http_timeout) as resp:
					return json.loads(resp.read().decode())
			else:
				raise ValueError(f"Unsupported method: {method}")
		except Exception as exc:
			# Логируем ошибку при возможности
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="error",
					message=f"RemotePluginProxy: {endpoint} failed: {str(exc)}",
				)
			except Exception:
				pass
			raise

	async def _fetch_metadata(self) -> dict:
		"""Получить метаданные удалённого плагина."""
		return await self._http_call("/plugin/metadata")

	@property
	def metadata(self) -> PluginMetadata:
		"""Вернуть метаданные (блокирующий вызов для property)."""
		# Это не идеально, но BasePlugin требует синхронный property
		# В реальности это заполняется асинхронно в on_load
		if self._metadata is None:
			return PluginMetadata(
				name="remote_plugin",
				version="0.0.0",
				description="Remote plugin proxy",
				author="Home Console",
			)
		return PluginMetadata(
			name=self._metadata.get("name", "remote_plugin"),
			version=self._metadata.get("version", "0.0.0"),
			description=self._metadata.get("description", ""),
			author=self._metadata.get("author", ""),
		)

	async def on_load(self) -> None:
		"""Загрузка: получить метаданные и вызвать /plugin/load на удалённом сервисе."""
		await super().on_load()
        
		try:
			# Получаем метаданные удалённого плагина
			self._metadata = await self._fetch_metadata()

			# Вызываем load на удалённом сервисе
			await self._http_call("/plugin/load", method="POST")

			# Зарегистрировать сервисы, описанные в метаданных
			services = self._metadata.get("services", []) if isinstance(self._metadata, dict) else []
			for svc in services:
				svc_name = svc.get("name")
				endpoint = svc.get("endpoint")
				method = svc.get("method", "POST").upper()
				if not svc_name or not endpoint:
					continue

				# Создать форвардер вызова на удалённый endpoint
				async def _make_forwarder(_endpoint=endpoint, _method=method):
					async def _forward(*args, **kwargs):
						payload = {"args": args, "kwargs": kwargs}
						# Прямой POST/GET к удалённому плагину
						if _method == "GET":
							return await self._http_call(_endpoint, method="GET")
						else:
							return await self._http_call(_endpoint, method="POST", json_data=payload)
					return _forward

				forwarder = await _make_forwarder()
				try:
					# Регистрируем сервис в runtime
					self.runtime.service_registry.register(svc_name, forwarder)
					self._registered_services.append(svc_name)
				except Exception:
					# Не ломаем загрузку, логируем и продолжаем
					try:
						await self.runtime.service_registry.call(
							"logger.log",
							level="warning",
							message=f"RemotePluginProxy: не удалось зарегистрировать сервис {svc_name}",
						)
					except Exception:
						pass

			# Логируем загрузку
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="info",
					message=f"Remote plugin '{self._metadata.get('name')}' loaded",
					plugin="RemotePluginProxy",
				)
			except Exception:
				pass
		except Exception as exc:
			# Не ломаем загрузку Core, но логируем ошибку
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="error",
					message=f"Failed to load remote plugin: {str(exc)}",
					plugin="RemotePluginProxy",
				)
			except Exception:
				pass
			raise

	async def on_start(self) -> None:
		"""Запуск: вызвать /plugin/start на удалённом сервисе."""
		await super().on_start()
        
		try:
			await self._http_call("/plugin/start", method="POST")
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="info",
					message=f"Remote plugin '{self.metadata.name}' started",
					plugin="RemotePluginProxy",
				)
			except Exception:
				pass
		except Exception as exc:
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="error",
					message=f"Failed to start remote plugin: {str(exc)}",
					plugin="RemotePluginProxy",
				)
			except Exception:
				pass

	async def on_stop(self) -> None:
		"""Остановка: вызвать /plugin/stop на удалённом сервисе."""
		await super().on_stop()
        
		try:
			await self._http_call("/plugin/stop", method="POST")
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="info",
					message=f"Remote plugin '{self.metadata.name}' stopped",
					plugin="RemotePluginProxy",
				)
			except Exception:
				pass
		except Exception as exc:
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="error",
					message=f"Failed to stop remote plugin: {str(exc)}",
					plugin="RemotePluginProxy",
				)
			except Exception:
				pass

	async def on_unload(self) -> None:
		"""Выгрузка: вызвать /plugin/unload на удалённом сервисе."""
		await super().on_unload()
		# Попытаться уведомить remote о выгрузке, но В ЛЮБОМ СЛУЧАЕ удалить зарегистрированные сервисы
		try:
			await self._http_call("/plugin/unload", method="POST")
		except Exception as exc:
			try:
				await self.runtime.service_registry.call(
					"logger.log",
					level="warning",
					message=f"Failed to unload remote plugin: {str(exc)}",
					plugin="RemotePluginProxy",
				)
			except Exception:
				pass

		# Отрегистировать сервисы, которые мы регистрировали при загрузке (гарантированно)
		for svc_name in list(self._registered_services):
			try:
				self.runtime.service_registry.unregister(svc_name)
			except Exception:
				pass
		self._registered_services.clear()

