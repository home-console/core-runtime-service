# Основные правила разработки ядра

Дата фиксации: 28 марта 2026

## 1. Инвариант ядра
`core` — тупой и детерминированный execution kernel.

Ядро:
- исполняет pipeline;
- вызывает контракты (`hooks`, `actions`, `handler`);
- сохраняет результат.

Ядро не принимает доменные решения.

## 2. Что запрещено в core
- Retry/backoff/policy-логика.
- Интерпретация ошибок и классификация причин.
- Routing/provider selection/fallback.
- Вычисление derived-полей (`retry_reason`, `triggered_by` и т.п.).
- Импорты `modules.*` из `core`.
- Скрытые “умные” ветки по бизнес-смыслу.

## 3. Где живет логика
- `modules` — единственный источник бизнес-логики.
- `app/bootstrap` — только composition/wiring.
- `plugins` — только через API-границу (`BasePlugin` helpers / `runtime.api` / thin runtime methods).

## 4. Правила переносимости ядра на другой ЯП
- В ядре только явные контракты и примитивы, без Python-магии.
- Никакой неявной регистрации и side effects на import.
- Модели — только данные (без доменных методов).
- Storage — read/write + atomic ops, без inference.
- Минимум глобального состояния; максимум явной инъекции зависимостей.

## 5. Правило про Stage/Phase/Step
- В production-коде ядра не использовать служебные метки разработки (`Step N`, `Stage N`, `Phase N`).
- В runtime-контексте и storage не хранить “этапность” как бизнес-семантику.

## 6. Базовый PR-чеклист
- Нет новых импортов `modules.*` в `core`.
- Нет доменной логики в `core`.
- Нет прямого доступа плагинов к внутренностям runtime (`service_registry/event_bus/storage/http/operations`).
- Архитектурный валидатор зелёный:
  `python3 scripts/validate_architecture_rules.py --root .`
