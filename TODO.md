# TODO / Roadmap

## Текущий статус: v0.1.0 (MVP)

✅ Реализовано:
- EventBus (pub/sub)
- ServiceRegistry (RPC)
- StateEngine (in-memory state)
- Storage API (key-value)
- PluginManager (lifecycle)
- SQLite адаптер
- Базовый класс плагина
- Пример плагина
- Документация

---

## Фаза 1: Стабилизация ядра

### Высокий приоритет

- [ ] **Логирование**
  - Структурированное логирование (JSON)
  - Уровни логов (DEBUG, INFO, WARNING, ERROR)
  - Rotation логов

- [ ] **Обработка ошибок**
  - Graceful shutdown при критических ошибках
  - Retry механизмы для Storage
  - Error boundaries для плагинов

- [ ] **Тесты**
  - Юнит-тесты всех компонентов
  - Интеграционные тесты с плагинами
  - Coverage > 80%

- [ ] **Мониторинг**
  - Метрики производительности
  - Health check endpoint
  - Статистика событий/сервисов

### Средний приоритет

- [ ] **Конфигурация**
  - YAML/TOML конфиг файлы
  - Валидация конфигурации
  - Hot reload конфигурации

- [ ] **Улучшения Storage API**
  - Batch операции (set_many, get_many)
  - Фильтрация по prefix
  - Pagination для list_keys
  - TTL для записей

- [ ] **EventBus улучшения**
  - Event filtering
  - Priority subscribers
  - Event history (опционально)

---

## Фаза 2: Production-ready

### Высокий приоритет

- [ ] **Персистентность**
  - Сохранение состояния StateEngine (опционально)
  - Event log для EventBus
  - Transaction log для Storage

- [ ] **Безопасность**
  - Изоляция плагинов (sandboxing)
  - Rate limiting для сервисов
  - Валидация данных событий

- [ ] **Производительность**
  - Кэширование в Storage API
  - Connection pooling для БД
  - Async batch processing

- [ ] **Надёжность**
  - Graceful degradation
  - Circuit breaker для сервисов
  - Automatic plugin restart при сбое

### Средний приоритет

- [ ] **Новые адаптеры**
  - PostgreSQL adapter
  - Redis adapter
  - MongoDB adapter (опционально)

- [ ] **Плагины для разработки**
  - Debug plugin (логирование всех событий)
  - Metrics plugin (Prometheus)
  - Health check plugin

- [ ] **CLI инструменты**
  - Управление плагинами (load, unload, restart)
  - Просмотр состояния Runtime
  - Отладка событий/сервисов

---

## Фаза 3: Remote Plugins

### Высокий приоритет

- [ ] **gRPC интеграция**
  - Proto файлы для контрактов
  - gRPC сервер в Core Runtime
  - gRPC клиент для remote плагинов

- [ ] **Remote Plugin Manager**
  - Регистрация remote плагинов
  - Health checking удалённых плагинов
  - Автоматический reconnect

- [ ] **Распределённые события**
  - Event streaming через gRPC
  - Event ordering гарантии
  - At-least-once delivery

### Средний приоритет

- [ ] **Service mesh**
  - Load balancing для remote сервисов
  - Service discovery
  - Failover механизмы

- [ ] **Distributed Storage**
  - Distributed transactions
  - Consistency guarantees
  - Sharding поддержка

---

## Фаза 4: Масштабирование

### Высокий приоритет

- [ ] **Кластеризация**
  - Multiple Runtime instances
  - Shared state через Redis/etcd
  - Leader election

- [ ] **Message Queue**
  - RabbitMQ/Kafka интеграция
  - Distributed EventBus
  - Event replay

- [ ] **Observability**
  - Distributed tracing (Jaeger/Zipkin)
  - Centralized logging (ELK)
  - Metrics aggregation

### Средний приоритет

- [ ] **API Gateway плагин**
  - REST API для управления Runtime
  - WebSocket для real-time events
  - GraphQL (опционально)

- [ ] **Аутентификация плагин**
  - JWT токены
  - OAuth2 интеграция
  - Permissions система

---

## Фаза 5: Экосистема

### Высокий приоритет

- [ ] **Plugin Marketplace**
  - Репозиторий плагинов
  - Версионирование
  - Dependency management

- [ ] **Документация**
  - Интерактивные туториалы
  - API референс
  - Best practices гайд

- [ ] **Tooling**
  - Plugin generator CLI
  - Plugin тестирование framework
  - IDE расширения

### Средний приоритет

- [ ] **Примеры плагинов**
  - Devices plugin (Zigbee, Z-Wave)
  - Users & Auth plugin
  - Automation plugin
  - Notifications plugin
  - Analytics plugin

- [ ] **Community**
  - Contributing guide
  - Code of conduct
  - Issue templates

---

## Долгосрочные идеи

### Исследование

- [ ] **WebAssembly плагины**
  - Безопасная изоляция
  - Multi-language поддержка
  - Sandboxing

- [ ] **Machine Learning интеграция**
  - ML models как плагины
  - Inference сервисы
  - Training pipeline

- [ ] **Edge computing**
  - Runtime на edge устройствах
  - Sync между edge и cloud
  - Offline-first режим

- [ ] **Time-series оптимизации**
  - Специализированный Storage для time-series
  - Aggregation queries
  - Downsampling

---

## НЕ планируется (out of scope)

❌ **ORM в Core** — используй Storage API  
❌ **Бизнес-логика в Core** — создай плагин  
❌ **FastAPI в Core** — создай API Gateway плагин  
❌ **Фронтенд** — это отдельный проект  
❌ **Мобильные приложения** — это отдельный проект

---

## Как внести вклад

1. Выбери задачу из TODO
2. Создай issue с описанием
3. Получи одобрение архитектуры
4. Создай PR с реализацией
5. Добавь тесты
6. Обнови документацию

**Принцип:** Всегда выбирай решение, которое делает ядро МЕНЬШЕ и ГЛУПЕЕ.

---

## Версионирование

Следуем Semantic Versioning:

- `v0.x.x` — MVP, breaking changes возможны
- `v1.x.x` — Stable API, backwards compatible
- `v2.x.x` — Major breaking changes

---

Последнее обновление: 2026-01-06
