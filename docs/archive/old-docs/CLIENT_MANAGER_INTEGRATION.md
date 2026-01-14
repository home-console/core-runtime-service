# Client Manager Integration

> **Статус:** План интеграции  
> **Сложность:** Средняя

---

## Обзор

Client Manager Service — standalone FastAPI приложение, управляющее удалёнными клиентами через WebSocket.

**Расположение:** `plugins/client-manager-service/`

---

## Интеграция

### Вариант 1: Плагин с отдельным uvicorn сервером (рекомендуется)

**Плюсы:**
- Минимальные изменения в client-manager-service
- Изоляция (отдельный порт, отдельный процесс)
- Легко отключить/включить

**Реализация:**

1. Создать структуру плагина:
```
plugins/client_manager/
├── __init__.py
├── plugin.py              # Основной плагин
└── plugin.json            # Manifest
```

2. Manifest (`plugin.json`):
```json
{
  "class_path": "plugins.client_manager.plugin.ClientManagerPlugin",
  "name": "client_manager",
  "version": "1.0.0",
  "description": "Client Manager Service - управление удалёнными клиентами",
  "dependencies": []
}
```

3. Плагин (`plugin.py`):
```python
import threading
import uvicorn
from core.base_plugin import BasePlugin, PluginMetadata

class ClientManagerPlugin(BasePlugin):
    def __init__(self, runtime=None):
        super().__init__(runtime)
        self._server = None
        self._thread = None
        self._app = None
    
    async def on_load(self):
        from plugins.client_manager_service.app.main import create_app
        self._app = create_app()
    
    async def on_start(self):
        host = self.get_env_config("CLIENT_MANAGER_HOST", default="0.0.0.0")
        port = self.get_env_config_int("CLIENT_MANAGER_PORT", default=10000)
        
        config = uvicorn.Config(self._app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        self._server = server
        
        def run_server():
            server.run()
        
        self._thread = threading.Thread(target=run_server, daemon=True)
        self._thread.start()
    
    async def on_stop(self):
        if self._server:
            self._server.should_exit = True
        if self._thread:
            await asyncio.to_thread(self._thread.join, timeout=2)
```

### Вариант 2: Интеграция в ApiModule (mount sub-app)

Если нужен один HTTP сервер:

```python
# modules/api/module.py
async def start(self):
    # ... существующий код ...
    
    if "client_manager" in self.runtime.plugin_manager.list_plugins():
        from plugins.client_manager_service.app.main import create_app
        client_manager_app = create_app()
        self.app.mount("/client-manager", client_manager_app)
```

---

## Потенциальные проблемы

### Импорты

**Проблема:** `client-manager-service` использует абсолютные импорты

**Решение:**
```python
import sys
from pathlib import Path

client_manager_path = Path(__file__).parent.parent / "client-manager-service"
if str(client_manager_path) not in sys.path:
    sys.path.insert(0, str(client_manager_path))
```

### Конфигурация

Использовать переменные окружения:
- `CLIENT_MANAGER_HOST` (default: `0.0.0.0`)
- `CLIENT_MANAGER_PORT` (default: `10000`)

---

## Проверка

```bash
# 1. Запустить runtime
python3 main.py

# 2. Проверить, что плагин загружен
curl http://localhost:8000/api/admin/v1/plugins

# 3. Проверить, что Client Manager работает
curl http://localhost:10000/health
curl http://localhost:10000/api/clients
```

---

## См. также

- [08-PLUGIN-CONTRACT.md](08-PLUGIN-CONTRACT.md) — контракт плагинов
- [modules/api/module.py](../modules/api/module.py) — пример запуска uvicorn в модуле
