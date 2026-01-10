# Примеры кода: Интеграция yandex_smart_home_real_v0

## Оглавление

1. [Инициализация Runtime](#инициализация-runtime)
2. [HTTP Endpoints](#http-endpoints)
3. [Обработка событий](#обработка-событий)
4. [Периодическая синхронизация](#периодическая-синхронизация)
5. [UI Integration](#ui-integration)
6. [Полный пример](#полный-пример)

---

## Инициализация Runtime

### Пример 1: Базовая инициализация

```python
# console.py или main.py

import asyncio
from pathlib import Path
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import AsyncSqliteStorage
from plugins.test import SystemLoggerPlugin
from plugins.oauth_yandex import OAuthYandexPlugin
from plugins.yandex_smart_home import YandexSmartHomeRealPlugin
from plugins.devices_plugin import DevicesPlugin

async def initialize_runtime():
    # Инициализировать storage
    db_path = Path(__file__).parent / "data" / "console.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage = AsyncSqliteStorage(str(db_path))
    
    # Создать runtime
    runtime = CoreRuntime(storage)
    
    # Загрузить плагины в правильном порядке
    plugins = [
        ("system_logger", SystemLoggerPlugin(runtime)),
        ("oauth_yandex", OAuthYandexPlugin(runtime)),
        ("devices", DevicesPlugin(runtime)),
        ("yandex_smart_home_real", YandexSmartHomeRealPlugin(runtime)),
    ]
    
    for plugin_name, plugin_instance in plugins:
        print(f"Loading {plugin_name}...")
        await runtime.plugin_manager.load_plugin(plugin_instance)
        await runtime.plugin_manager.start_plugin(plugin_name)
    
    return runtime

async def main():
    runtime = await initialize_runtime()
    
    # Запустить HTTP сервер
    await runtime.start()
    
    # Обработчик сигналов для graceful shutdown
    import signal
    
    def signal_handler(sig, frame):
        asyncio.create_task(cleanup(runtime))
    
    signal.signal(signal.SIGINT, signal_handler)

async def cleanup(runtime):
    print("Shutting down...")
    await runtime.stop()
    await runtime.storage.close()

if __name__ == "__main__":
    asyncio.run(main())
```

### Пример 2: Конфигурируемая инициализация

```python
# config.py

import os
from enum import Enum

class YandexMode(Enum):
    STUB = "stub"
    REAL = "real"

YANDEX_MODE = YandexMode(os.getenv("YANDEX_MODE", "stub").lower())

# console.py

async def initialize_yandex_plugin(runtime):
    """Загрузить Яндекс плагин в зависимости от режима."""
    
    if YANDEX_MODE == YandexMode.REAL:
        from plugins.yandex_smart_home import YandexSmartHomeRealPlugin
        plugin = YandexSmartHomeRealPlugin(runtime)
        print("Loading REAL Yandex plugin")
    else:
        from plugins.test import YandexSmartHomeStubPlugin
        plugin = YandexSmartHomeStubPlugin(runtime)
        print("Loading STUB Yandex plugin")
    
    await runtime.plugin_manager.load_plugin(plugin)
    await runtime.plugin_manager.start_plugin(plugin.metadata.name)
    
    return plugin

# Использование
async def main():
    runtime = CoreRuntime(storage)
    
    # ... загрузить другие плагины ...
    
    await initialize_yandex_plugin(runtime)
    
    # ... остальной код ...
```

---

## HTTP Endpoints

### Пример 1: Sync devices endpoint

```python
# api_gateway_plugin.py или отдельный модуль

from typing import Any, Dict

async def handle_sync_devices(runtime):
    """HTTP endpoint: POST /api/yandex/sync-devices"""
    
    try:
        # Проверить, что OAuth авторизован
        oauth_status = await runtime.service_registry.call("oauth_yandex.get_status")
        
        if not oauth_status.get("authorized"):
            return {
                "status": "error",
                "message": "Не авторизованы в Яндексе",
                "action": "redirect_to_oauth"
            }, 401
        
        # Синхронизировать устройства
        devices = await runtime.service_registry.call("yandex.sync_devices")
        
        return {
            "status": "success",
            "count": len(devices),
            "devices": devices,
        }, 200
    
    except ValueError as e:
        return {
            "status": "error",
            "message": str(e),
        }, 400
    
    except RuntimeError as e:
        error_msg = str(e)
        
        if "HTTP 401" in error_msg:
            return {
                "status": "error",
                "message": "Токен истёк. Переавторизуйтесь",
                "action": "redirect_to_oauth"
            }, 401
        
        return {
            "status": "error",
            "message": str(e),
        }, 500
    
    except Exception as e:
        return {
            "status": "error",
            "message": "Неожиданная ошибка",
        }, 500
```

### Пример 2: Device status endpoint

```python
async def handle_get_device_status(runtime, device_id: str):
    """HTTP endpoint: GET /api/devices/{device_id}/status"""
    
    # Получить устройство из state_engine
    device = await runtime.state_engine.get(f"external_devices.{device_id}")
    
    if not device:
        return {"error": "Device not found"}, 404
    
    return {
        "device_id": device_id,
        "type": device.get("type"),
        "state": device.get("state"),
        "capabilities": device.get("capabilities"),
    }, 200
```

### Пример 3: Sync status endpoint

```python
async def handle_get_sync_status(runtime):
    """HTTP endpoint: GET /api/yandex/sync-status"""
    
    # Получить информацию о последней синхронизации
    last_sync_info = await runtime.state_engine.get("yandex.last_sync")
    
    if not last_sync_info:
        return {
            "status": "never_synced",
            "device_count": 0,
        }, 200
    
    return {
        "status": "synced",
        "last_sync_time": last_sync_info.get("timestamp"),
        "device_count": last_sync_info.get("device_count"),
        "next_sync": last_sync_info.get("next_sync"),
    }, 200
```

---

## Обработка событий

### Пример 1: Подписка на события обнаружения

```python
# В плагине или при инициализации

async def setup_device_discovery_listener(runtime):
    """Подписаться на события об обнаружении устройств."""
    
    async def on_device_discovered(event_type: str, data: dict):
        """Обработчик события external.device_discovered."""
        
        device_id = data.get("external_id")
        device_type = data.get("type")
        
        print(f"[DISCOVER] Device: {device_id} ({device_type})")
        
        # Сохранить в state_engine для дальнейшей обработки
        await runtime.state_engine.set(
            f"external_devices.{device_id}",
            data
        )
        
        # Логировать
        try:
            await runtime.service_registry.call(
                "logger.log",
                level="info",
                message=f"External device discovered: {device_id}",
                context={"device": data},
            )
        except Exception:
            pass
    
    # Подписаться
    runtime.event_bus.subscribe("external.device_discovered", on_device_discovered)
```

### Пример 2: Обновление маппинга после синхронизации

```python
async def auto_map_external_devices(runtime):
    """Автоматически создать mappings для новых устройств."""
    
    async def on_device_discovered(event_type: str, data: dict):
        external_id = data.get("external_id")
        device_type = data.get("type")
        
        # Создать internal device ID (можно использовать хеш)
        import hashlib
        internal_id = f"yandex_{hashlib.md5(external_id.encode()).hexdigest()[:8]}"
        
        # Создать маппинг
        try:
            await runtime.service_registry.call(
                "devices.map_external_device",
                external_id,
                internal_id
            )
        except Exception as e:
            print(f"Failed to map device {external_id}: {e}")
    
    runtime.event_bus.subscribe("external.device_discovered", on_device_discovered)
```

---

## Периодическая синхронизация

### Пример 1: Синхронизация по расписанию

```python
import asyncio
import time
from datetime import datetime, timedelta

class ScheduledSync:
    def __init__(self, runtime, interval_minutes=60):
        self.runtime = runtime
        self.interval = interval_minutes * 60  # В секунды
        self.running = False
    
    async def start(self):
        """Запустить периодическую синхронизацию."""
        self.running = True
        asyncio.create_task(self._sync_loop())
    
    async def stop(self):
        """Остановить периодическую синхронизацию."""
        self.running = False
    
    async def _sync_loop(self):
        """Основной цикл синхронизации."""
        
        while self.running:
            try:
                start = time.time()
                
                # Выполнить синхронизацию
                devices = await self.runtime.service_registry.call(
                    "yandex.sync_devices"
                )
                
                duration = time.time() - start
                
                # Сохранить информацию о синхронизации
                await self.runtime.state_engine.set(
                    "yandex.last_sync",
                    {
                        "timestamp": datetime.now().isoformat(),
                        "device_count": len(devices),
                        "duration_seconds": duration,
                        "status": "success",
                        "next_sync": (
                            datetime.now() + timedelta(seconds=self.interval)
                        ).isoformat(),
                    }
                )
                
                # Логировать
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="info",
                        message=f"Scheduled sync completed: {len(devices)} devices",
                        context={
                            "duration_ms": int(duration * 1000),
                        }
                    )
                except Exception:
                    pass
            
            except Exception as e:
                # Логировать ошибку (но не останавливать цикл)
                try:
                    await self.runtime.service_registry.call(
                        "logger.log",
                        level="error",
                        message=f"Scheduled sync failed: {str(e)}",
                    )
                except Exception:
                    pass
            
            finally:
                # Ждать перед следующей синхронизацией
                await asyncio.sleep(self.interval)

# Использование
async def main():
    runtime = CoreRuntime(storage)
    
    # ... инициализировать плагины ...
    
    # Запустить периодическую синхронизацию
    sync_scheduler = ScheduledSync(runtime, interval_minutes=60)
    await sync_scheduler.start()
    
    # ... остальной код ...
    
    # При выходе
    await sync_scheduler.stop()
```

### Пример 2: Синхронизация при авторизации

```python
# Добавить в oauth_yandex plugin или в отдельный listener

async def sync_on_oauth_complete(runtime):
    """Синхронизировать устройства после успешной авторизации."""
    
    async def on_oauth_updated(event_type: str, data: dict):
        """Обработчик события об обновлении OAuth статуса."""
        
        oauth_status = data.get("status")
        
        if oauth_status == "authorized":
            # Авторизация завершена, синхронизировать устройства
            try:
                devices = await runtime.service_registry.call(
                    "yandex.sync_devices"
                )
                
                print(f"Auto-synced {len(devices)} devices after OAuth")
                
            except Exception as e:
                print(f"Auto-sync failed: {e}")
    
    # Подписаться (если такое событие будет публиковать oauth_yandex)
    # runtime.event_bus.subscribe("oauth.status_changed", on_oauth_updated)
```

---

## UI Integration

### Пример 1: React компонент для синхронизации

```typescript
// SyncDevicesButton.tsx

import { useState } from 'react';
import { syncDevices } from '../api/yandex';

export function SyncDevicesButton() {
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleSync = async () => {
    try {
      setLoading(true);
      setError(null);
      setMessage(null);

      const response = await syncDevices();

      if (response.status === 'success') {
        setMessage(
          `✓ Синхронизировано ${response.count} устройств`
        );
      } else if (response.action === 'redirect_to_oauth') {
        // Перенаправить на OAuth страницу
        window.location.href = '/oauth';
      } else {
        setError(response.message || 'Ошибка синхронизации');
      }
    } catch (err) {
      setError(`Ошибка: ${err instanceof Error ? err.message : 'Неизвестная ошибка'}`);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ marginTop: '20px' }}>
      <button
        onClick={handleSync}
        disabled={loading}
        style={{
          padding: '10px 20px',
          backgroundColor: '#007bff',
          color: 'white',
          border: 'none',
          borderRadius: '4px',
          cursor: loading ? 'not-allowed' : 'pointer',
        }}
      >
        {loading ? 'Синхронизация...' : 'Синхронизировать устройства'}
      </button>

      {message && (
        <div style={{ color: 'green', marginTop: '10px' }}>
          {message}
        </div>
      )}

      {error && (
        <div style={{ color: 'red', marginTop: '10px' }}>
          {error}
        </div>
      )}
    </div>
  );
}
```

### Пример 2: API функции

```typescript
// api/yandex.ts

interface SyncResponse {
  status: 'success' | 'error' | 'unauthorized' | 'token_expired';
  count?: number;
  message?: string;
  action?: 'redirect_to_oauth';
  devices?: any[];
}

export async function syncDevices(): Promise<SyncResponse> {
  const response = await fetch('/api/yandex/sync-devices', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      return {
        status: 'unauthorized',
        message: 'Не авторизованы в Яндексе',
        action: 'redirect_to_oauth',
      };
    }
    throw new Error(`HTTP ${response.status}`);
  }

  return await response.json();
}

export async function getSyncStatus() {
  const response = await fetch('/api/yandex/sync-status');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return await response.json();
}
```

---

## Полный пример

### Интеграция всего вместе

```python
# main.py - полная интеграция

import asyncio
import signal
from pathlib import Path
from core.runtime import CoreRuntime
from adapters.sqlite_adapter import AsyncSqliteStorage
from plugins.test import SystemLoggerPlugin
from plugins.oauth_yandex import OAuthYandexPlugin
from plugins.yandex_smart_home import YandexSmartHomeRealPlugin
from plugins.devices_plugin import DevicesPlugin
from plugins.api_gateway_plugin import ApiGatewayPlugin

class Application:
    def __init__(self):
        self.runtime = None
        self.sync_scheduler = None
    
    async def initialize(self):
        """Инициализировать приложение."""
        
        print("Initializing application...")
        
        # 1. Инициализировать storage
        db_path = Path(__file__).parent / "data" / "console.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        storage = AsyncSqliteStorage(str(db_path))
        
        # 2. Создать runtime
        self.runtime = CoreRuntime(storage)
        
        # 3. Загрузить плагины
        plugins_to_load = [
            ("system_logger", SystemLoggerPlugin(self.runtime)),
            ("oauth_yandex", OAuthYandexPlugin(self.runtime)),
            ("devices", DevicesPlugin(self.runtime)),
            ("yandex_smart_home_real", YandexSmartHomeRealPlugin(self.runtime)),
            ("api_gateway", ApiGatewayPlugin(self.runtime)),
        ]
        
        for plugin_name, plugin_instance in plugins_to_load:
            print(f"  Loading {plugin_name}...")
            await self.runtime.plugin_manager.load_plugin(plugin_instance)
            await self.runtime.plugin_manager.start_plugin(plugin_name)
        
        # 4. Установить обработчики событий
        await self._setup_event_handlers()
        
        # 5. Запустить периодическую синхронизацию
        await self._setup_scheduled_sync()
        
        # 6. Запустить HTTP сервер
        await self.runtime.start()
        
        print("Application initialized successfully!")
    
    async def _setup_event_handlers(self):
        """Установить обработчики событий."""
        
        async def on_device_discovered(event_type: str, data: dict):
            device_id = data.get("external_id")
            print(f"[EVENT] Device discovered: {device_id}")
            
            # Сохранить в state_engine
            await self.runtime.state_engine.set(
                f"external_devices.{device_id}",
                data
            )
        
        self.runtime.event_bus.subscribe(
            "external.device_discovered",
            on_device_discovered
        )
    
    async def _setup_scheduled_sync(self):
        """Установить периодическую синхронизацию."""
        
        async def sync_loop():
            while True:
                try:
                    # Проверить OAuth статус
                    oauth_status = await self.runtime.service_registry.call(
                        "oauth_yandex.get_status"
                    )
                    
                    if oauth_status.get("authorized"):
                        # Синхронизировать устройства
                        devices = await self.runtime.service_registry.call(
                            "yandex.sync_devices"
                        )
                        print(f"[SYNC] Synced {len(devices)} devices")
                
                except Exception as e:
                    print(f"[ERROR] Sync failed: {e}")
                
                finally:
                    # Ждать 1 час перед следующей синхронизацией
                    await asyncio.sleep(3600)
        
        asyncio.create_task(sync_loop())
    
    async def shutdown(self):
        """Корректно выключить приложение."""
        print("Shutting down...")
        await self.runtime.stop()
        await self.runtime.storage.close()
        print("Shutdown complete!")

async def main():
    app = Application()
    
    # Инициализировать
    await app.initialize()
    
    # Обработчик сигналов
    def signal_handler(sig, frame):
        print(f"Received signal {sig}")
        asyncio.create_task(app.shutdown())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Ждать (будет блокироваться на runtime.start())
    # или можно использовать asyncio.Event() для более kontroly

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Заключение

Эти примеры показывают как интегрировать `yandex_smart_home_real_v0` плагин в ваше приложение.

Ключевые моменты:
- ✅ Загружать плагины в правильном порядке
- ✅ Обрабатывать ошибки OAuth и API
- ✅ Подписываться на события об обнаружении
- ✅ Предоставлять HTTP endpoints для синхронизации
- ✅ Логировать и мониторить
- ✅ Использовать асинхронные операции

Enjoy! 🚀
