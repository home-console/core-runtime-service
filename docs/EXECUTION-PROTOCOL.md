## Execution Protocol (D3)

**Статус:** Stable (D3.1.1)  
**Цель:** единый контракт между *transport backend* (container/process/remote/wasm) и *execution environment* (runner).

Execution environment — это минимальная среда, которая принимает **операцию** и возвращает **результат**, не зная:
- Core Runtime
- доменов / модулей
- плагинов / capabilities
- admin / UI / automation

Backend — это транспорт, который запускает environment (процесс/контейнер/удалённо) и прокидывает stdin/stdout.

---

### 1) Input (stdin → runner)

JSON объект:

```json
{
  "operation_type": "string",
  "params": { "any": "json" },
  "context": {
    "request_id": "string | null",
    "caller": "string | null",
    "metadata": { "any": "json" }
  },
  "timeout": 30
}
```

**Правила:**
- `operation_type`: opaque string (runner не интерпретирует семантику).
- `params`: только JSON-значения.
- `context`: opaque blob; runner не интерпретирует и не ветвится по нему.
- `timeout`: секунды; transport backend обязан применить timeout, если умеет.
- В payload **нельзя** передавать доменные термины (plugins/capabilities/admin/automation).

---

### 2) Output (stdout ← runner)

JSON объект:

```json
{
  "status": "ok",
  "result": { "any": "json" }
}
```

или

```json
{
  "status": "error",
  "error": {
    "code": "string",
    "message": "string",
    "details": { "any": "json" }
  }
}
```

**Правила:**
- stdout **всегда** должен быть валидным JSON.
- `status="ok"` → поле `result` обязательно.
- `status="error"` → поле `error` обязательно.
- runner не пишет traceback в stdout (может писать в stderr).

