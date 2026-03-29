🧠 ТЗ: Kernel v1 (финальная версия)

⸻

🎯 0. Цель

Создать минимальное, изолированное runtime-ядро, которое:
	•	не зависит от modules
	•	не содержит бизнес-логики
	•	может быть переписано на Go без изменения внешнего API

⸻

🧩 1. Архитектура системы

kernel ← modules ← plugins


⸻

📌 Правило зависимостей (ОБЯЗАТЕЛЬНО)

kernel НЕ импортирует modules
modules НЕ импортируют plugins
plugins НЕ импортируют modules


⸻

🧱 2. Границы ядра

⸻

✅ Kernel включает ТОЛЬКО:

Runtime
	•	event loop
	•	dispatcher

Plugin system
	•	plugin_loader
	•	plugin_registry
	•	plugin_manager (ОДИН)

Core API
	•	KernelContext
	•	ServiceRegistry (упрощённый!)

State
	•	простой key-value store

⸻

❌ Kernel НЕ включает:
	•	storage
	•	policy
	•	security (кроме sandbox)
	•	execution
	•	http/api
	•	database
	•	observability
	•	ACL / authorization

⸻

🔌 3. Контракты ядра

⸻

3.1 Event

class Event:
    type: str
    payload: dict
    meta: dict


⸻

3.2 KernelContext

class KernelContext:
    def emit(self, event): ...
    def get_service(self, name: str): ...
    def get_state(self, key: str): ...
    def set_state(self, key: str, value): ...


⸻

3.3 RuntimeModule

class RuntimeModule:
    async def register(self, ctx): ...
    async def start(self, ctx): ...
    async def stop(self, ctx): ...


⸻

3.4 ServiceRegistry (строго минимальный)

class ServiceRegistry:
    async def register(self, name, func): ...
    async def call(self, name, *args, **kwargs): ...


⸻

❗ ServiceRegistry НЕ ДОЛЖЕН:
	•	знать про policy
	•	знать про ACL
	•	иметь middleware
	•	иметь бизнес-логику

⸻

🧩 4. Modules

⸻

📌 Определение

Modules = системная логика

⸻

Примеры:
	•	storage
	•	execution
	•	policy
	•	security
	•	http
	•	observability

⸻

📌 Правила:
	•	используют KernelContext
	•	регистрируют сервисы
	•	могут зависеть друг от друга (лучше через services)

⸻

🔌 5. Plugins

⸻

📌 Ограничения:
	•	только через context / SDK
	•	без прямых import modules
	•	sandbox

⸻

⚙️ 6. Взаимодействие

⸻

Единственный способ:

ctx.get_service("storage")


⸻

❌ Запрещено:

from modules.storage import ...


⸻

🔥 7. Ключевые принципы

⸻

RULE 1 — Kernel is dumb

ядро не принимает решений

⸻

RULE 2 — No domain knowledge

ядро не знает:
	•	storage
	•	policy
	•	execution

⸻

RULE 3 — Context is boundary

всё через context

⸻

RULE 4 — One implementation
	•	1 plugin manager
	•	1 storage
	•	1 policy

⸻

RULE 5 — Replaceability

любой module заменяем без изменения kernel

⸻

🧪 8. Архитектурные тесты

⸻

TEST 1

rg "import modules" core → 0


⸻

TEST 2

rg "import modules" plugins → 0


⸻

TEST 3

удалить modules/storage → kernel работает

⸻

TEST 4

kernel не содержит business logic

⸻

🚀 9. ПЛАН РЕФАКТОРИНГА (ПО РАЗДЕЛАМ)

⸻

🔴 РАЗДЕЛ 1 — ФИКСАЦИЯ ГРАНИЦ

Цель: остановить ухудшение

⸻

Сделать:
	•	добавить CI правило: запрет import modules в core/plugins
	•	зафиксировать текущий RuntimeContext как legacy
	•	создать новый KernelContext (пустой)

⸻

🟡 РАЗДЕЛ 2 — НОВЫЙ CONTEXT

Цель: убрать god object

⸻

Сделать:
	•	создать core/kernel/context.py
	•	реализовать:
	•	get_service
	•	emit
	•	state

⸻

НЕ трогать пока:
	•	старый RuntimeContext

⸻

🟡 РАЗДЕЛ 3 — УПРОЩЕНИЕ SERVICE REGISTRY

Цель: убрать бизнес-логику из ядра

⸻

Сделать:
	•	удалить:
	•	ACL
	•	policy
	•	middleware
	•	оставить только register + call

⸻

🟡 РАЗДЕЛ 4 — PLUGIN MANAGER

Цель: один источник правды

⸻

Сделать:
	•	создать core/kernel/plugin_manager.py
	•	удалить дубли

⸻

🟡 РАЗДЕЛ 5 — MODULE API

Цель: перевести модули на context

⸻

Сделать:
	•	заменить доступ:

ctx.storage → ctx.get_service("storage")


⸻

🟢 РАЗДЕЛ 6 — ВЫНОС MODULES

Цель: очистить ядро

⸻

Перенести:
	•	storage → modules/storage
	•	policy → modules/policy
	•	security → modules/security
	•	http → modules/api

⸻

🟢 РАЗДЕЛ 7 — УДАЛЕНИЕ LEGACY

⸻

Сделать:
	•	удалить RuntimeContext
	•	удалить дубли
	•	удалить старые manager’ы

⸻

🏁 10. Definition of Done

⸻

✔ kernel не знает про modules
✔ ServiceRegistry тупой
✔ RuntimeContext исчез
✔ только KernelContext
✔ нет прямых импортов
✔ система запускается

⸻

💡 Финальная мысль

❗ Ты не переписываешь систему
❗ Ты вырезаешь из неё ядро

