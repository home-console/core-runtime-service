Вот тебе чёткий инженерный план рефакторинга, который можно вставить в .md и использовать как roadmap.
Он разбит на этапы, с критериями завершения и без “размытости”.

⸻

:::writing{variant=“standard” id=“83421”}

🧱 CORE ARCHITECTURE REFACTOR PLAN

🎯 ЦЕЛЬ

Привести архитектуру проекта к строгой модели:
	•	core/ → platform engine (без доменной логики)
	•	modules/ → control plane (продуктовая логика)
	•	plugins/ → расширения

⸻

🧠 ГЛАВНЫЙ ПРИНЦИП

core ← modules ← plugins

❌ core не знает про modules
❌ modules не знают про plugins
❌ никакой бизнес-логики в core

⸻

🏗 ЭТАП 0 — ПОДГОТОВКА

Цель

Зафиксировать текущее состояние

Действия
	•	Сделать git commit (checkpoint)
	•	Запустить все тесты → убедиться что зелёные
	•	Зафиксировать baseline (pytest + e2e)

Done критерий

✔ тесты проходят
✔ можно откатиться

⸻

🧱 ЭТАП 1 — НОВАЯ СТРУКТУРА CORE

Цель

Разделить core на подсистемы

Создать директории

core/
    runtime/
    kernel/
    execution/
    storage/
    security/
    observability/
    messaging/
    config/
    utils/

Действия

Runtime
	•	runtime.py → core/runtime/runtime.py
	•	runtime_context.py → core/runtime/context.py
	•	runtime_module.py → core/runtime/module.py
	•	module_manager.py → core/runtime/module_manager.py

Kernel (plugins)
	•	core/kernel/* оставить
	•	base_plugin.py → core/kernel/base_plugin.py
	•	plugin_schema.py → core/kernel/plugin_schema.py

Messaging
	•	event_bus.py → core/messaging/event_bus.py
	•	service_registry.py → core/messaging/service_registry.py

Execution
	•	оставить core/execution/*
	•	execution_router.py → УДАЛИТЬ
	•	remote_executor.py → УДАЛИТЬ
	•	remote_provider.py → УДАЛИТЬ

Storage
	•	storage*.py → core/storage/
	•	secure_storage.py → core/storage/secure_storage.py

Security
	•	core/security/* оставить
	•	policy_engine.py → core/security/policy_engine.py
	•	удалить core/security.py (дубль)

Observability
	•	health_monitor.py → core/observability/health_monitor.py
	•	logger_helper.py → core/observability/logger.py

Config
	•	config.py → core/config/config.py

⸻

Done критерий

✔ core разбит на подсистемы
✔ нет “плоских” файлов в core/
✔ импорты работают

⸻

🚫 ЭТАП 2 — УДАЛЕНИЕ ДОМЕНА ИЗ CORE

Цель

Оставить core только как engine

⸻

Перенести в modules

Agents
	•	core/agent → modules/agents/
	•	core/agents → modules/agents/

Credentials
	•	core/credentials → modules/credentials/

Marketplace
	•	core/marketplace → modules/marketplace/

Operations
	•	core/operations → modules/operations/

⸻

Удалить / перенести

Adapters
	•	core/adapters → modules/api или modules/admin

HTTP
	•	http_registry.py → modules/api

Remote
	•	core/remote_executor.py → удалить
	•	core/remote_provider.py → удалить
	•	core/remote_services → modules/monitoring или удалить

⸻

Done критерий

✔ core НЕ содержит бизнес-логики
✔ в core нет agent / credential / marketplace

⸻

⚡ ЭТАП 3 — EXECUTION КАК ЦЕНТР

Цель

Сделать execution единым слоем выполнения

⸻

Действия

Добавить provider SSH
	•	создать core/execution/providers/ssh.py
	•	перенести modules/ssh/ssh_execution_service → туда

⸻

Унифицировать execution
	•	убедиться что:
	•	команды
	•	terminal
	•	SSH
	•	container

идут через execution

⸻

Удалить дубли
	•	execution_router → удалить
	•	remote_executor → удалить

⸻

Done критерий

✔ execution = единый вход для выполнения
✔ нет дублирующих механизмов

⸻

🤖 ЭТАП 4 — AGENTS В MODULES

Цель

Собрать агентную систему в одном месте

⸻

Структура

modules/agents/
    registry.py
    enrollment.py
    deploy_service.py
    health.py


⸻

Действия
	•	объединить:
	•	core/agent
	•	modules/agent
	•	modules/agents
	•	удалить дубли

⸻

Done критерий

✔ один source of truth для agents
✔ нет agent логики в core

⸻

🔌 ЭТАП 5 — ОЧИСТКА ADMIN

Цель

убрать infra из admin

⸻

Действия
	•	удалить SSH из:
modules/admin/services/ssh_terminal.py
	•	заменить на execution вызовы

⸻

Done критерий

✔ admin не содержит SSH логики
✔ admin только orchestration

⸻

🌐 ЭТАП 6 — API СЛОЙ

Цель

изолировать HTTP

⸻

Действия
	•	modules/api оставить как adapter
	•	убрать бизнес-логику из API
	•	API вызывает только services

⸻

Done критерий

✔ API тонкий слой
✔ нет логики внутри

⸻

🧠 ЭТАП 7 — DEPENDENCY RULES

Правила

core → НИКОГО
modules → core
plugins → modules + core


⸻

Проверка
	•	нет import modules в core
	•	нет import plugins в modules
	•	plugins используют только public API

⸻

Done критерий

✔ архитектура направленная
✔ нет циклов

⸻

🧪 ЭТАП 8 — ТЕСТЫ

Действия
	•	запустить pytest
	•	исправить импорты
	•	проверить integration тесты

⸻

Done критерий

✔ все тесты зелёные

⸻

🧱 ЭТАП 9 — ФИНАЛЬНАЯ СТРУКТУРА

core/
    runtime/
    kernel/
    execution/
    storage/
    security/
    observability/
    messaging/
    config/

modules/
    agents/
    devices/
    automation/
    credentials/
    integrations/
    admin/
    api/

plugins/
    ...


⸻

🚀 РЕЗУЛЬТАТ

После выполнения:

✔ ядро станет стабильным engine
✔ модули станут чистым control plane
✔ execution станет центром системы
✔ плагины будут расширяемыми

⸻

🧠 ВАЖНО

Не делать всё сразу.

Правильный порядок:
	1.	core структура
	2.	удаление домена
	3.	execution
	4.	agents
	5.	admin
	6.	api

⸻

🔥 ФИНАЛ

Если после каждого этапа:
	•	тесты зелёные
	•	архитектура упрощается

→ ты идёшь правильно
:::

⸻

Если хочешь, дальше могу:
	•	сделать чеклист с git-командами (mv + sed для импортов)
	•	или дать скрипт, который полуавтоматически всё разнесёт