🧠 ТЗ: Архитектура ядра (Kernel Specification v1)

⸻

🎯 0. Цель

Построить минимальное, изолированное, переносимое ядро, которое:
	•	не зависит от бизнес-логики
	•	не зависит от модулей
	•	может быть переписано на другой язык без изменения API

⸻

🧩 1. Архитектурная модель

kernel ← modules ← plugins


⸻

📌 Правило зависимостей (ОБЯЗАТЕЛЬНО)

kernel НЕ импортирует modules
modules НЕ импортируют plugins
plugins НЕ импортируют modules


⸻

🧱 2. Состав ядра (Kernel Scope)

✅ В ядре РАЗРЕШЕНО:

2.1 Runtime
	•	event loop
	•	dispatcher

2.2 Plugin system
	•	plugin_loader
	•	plugin_registry
	•	plugin_manager (единственный!)

2.3 Context
	•	KernelContext (минимальный API)

2.4 State
	•	простой key-value store

⸻

❌ В ядре ЗАПРЕЩЕНО:
	•	storage реализации
	•	policy логика
	•	security (кроме sandbox)
	•	execution engine
	•	http / api
	•	database
	•	observability

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
    def emit(event): ...
    def get_service(name): ...
    def get_state(key): ...
    def set_state(key, value): ...


⸻

3.3 Plugin Interface

class Plugin:
    def handle_event(self, event, ctx): ...


⸻

🧩 4. Modules (вне ядра)

📌 Определение

Modules = системные компоненты

⸻

Примеры:
	•	storage
	•	execution
	•	policy
	•	security
	•	observability

⸻

📌 Правила:
	•	используют KernelContext
	•	регистрируются как services
	•	могут зависеть друг от друга (но лучше через contracts)

⸻

🔌 5. Plugins

📌 Определение

Plugins = пользовательские расширения

⸻

Ограничения:
	•	только через SDK / Context
	•	нет прямого доступа к modules
	•	sandbox

⸻

⚙️ 6. Service Access (ЕДИНЫЙ СПОСОБ)

⸻

❗ Любой доступ:

ctx.get_service("storage")


⸻

❌ Запрещено:

from modules.storage import ...


⸻

🔥 7. Ключевые правила (обязательные)

⸻

RULE 1 — Kernel is dumb

Ядро:
	•	не принимает решений
	•	не содержит бизнес-логики

⸻

RULE 2 — No direct imports

modules → plugins ❌
plugins → modules ❌
kernel → modules ❌


⸻

RULE 3 — Single responsibility
	•	1 plugin manager
	•	1 storage
	•	1 policy

⸻

RULE 4 — Replaceability

Любой модуль можно заменить без изменения ядра

⸻

RULE 5 — Context is boundary

Всё взаимодействие через context

⸻

🧪 8. Архитектурные тесты (обязательные)

⸻

TEST 1

Удалить modules/storage → kernel работает

⸻

TEST 2

Удалить modules/security → kernel работает

⸻

TEST 3

Плагин не может импортировать modules

⸻

TEST 4

Kernel не импортирует modules

⸻

🚫 9. Антипаттерны (запрещено)

⸻

❌ дубли manager’ов
❌ дубли storage
❌ дубли policy
❌ прямые вызовы между слоями
❌ “умный” runtime_context
❌ sdk завязанный на modules

⸻

🏗 10. Целевая структура проекта

core/
  kernel/
    event_bus.py
    runtime.py
    context.py
    plugin_manager.py

modules/
  storage/
  execution/
  policy/
  security/

plugins/
  *

sdk/   (позже)


⸻

🏁 11. Definition of Done

Архитектура считается правильной, если:
	•	kernel не знает про modules
	•	modules можно удалить без падения kernel
	•	plugins работают только через context
	•	нет прямых импортов между слоями

⸻

💡 12. Главный принцип

❗ Kernel = минимальный runtime
❗ Всё остальное = вне ядра

