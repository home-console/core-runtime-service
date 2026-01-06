# 📚 Core Runtime Service — Индекс документации

> **Минимальный kernel для plugin-first платформы умного дома**

---

## 🚀 Начало работы

### Новичкам
1. **[README.md](README.md)** — начните здесь! Основная документация, концепции, примеры
2. **[QUICKSTART.md](QUICKSTART.md)** — запустите за 5 минут, создайте первый плагин
3. **[Запустить demo](demo.py)** — `python3 demo.py` — посмотрите как это работает

### Разработчикам
4. **[ARCHITECTURE.md](ARCHITECTURE.md)** — архитектура, паттерны, решения
5. **[FILE_STRUCTURE.md](FILE_STRUCTURE.md)** — структура файлов, соглашения
6. **[TODO.md](TODO.md)** — roadmap, что планируется, как помочь

### Обзор
7. **[OVERVIEW.md](OVERVIEW.md)** — краткий обзор всего проекта

---

## 📖 Документация по темам

### Концепции
- **Что такое Core Runtime?** → [README.md#основная-цель](README.md)
- **Plugin-first архитектура** → [README.md#plugin-first-архитектура](README.md)
- **Философия** → [README.md#философия](README.md)
- **Архитектурные принципы** → [ARCHITECTURE.md#принципы-проектирования](ARCHITECTURE.md)

### Компоненты
- **EventBus** → [ARCHITECTURE.md#eventbus](ARCHITECTURE.md)
- **ServiceRegistry** → [ARCHITECTURE.md#serviceregistry](ARCHITECTURE.md)
- **StateEngine** → [ARCHITECTURE.md#stateengine](ARCHITECTURE.md)
- **Storage API** → [ARCHITECTURE.md#storage-api](ARCHITECTURE.md)
- **PluginManager** → [ARCHITECTURE.md#pluginmanager](ARCHITECTURE.md)

### Разработка плагинов
- **Создание плагина** → [README.md#создание-плагина](README.md)
- **Lifecycle плагина** → [README.md#lifecycle-плагина](README.md)
- **Пример плагина** → [plugins/example_plugin.py](plugins/example_plugin.py)
- **Базовый класс** → [plugins/base_plugin.py](plugins/base_plugin.py)

### Использование API
- **Storage API** → [QUICKSTART.md#storage-api](QUICKSTART.md)
- **EventBus** → [QUICKSTART.md#eventbus](QUICKSTART.md)
- **ServiceRegistry** → [QUICKSTART.md#serviceregistry](QUICKSTART.md)
- **StateEngine** → [QUICKSTART.md#stateengine](QUICKSTART.md)

### Расширение
- **Новые адаптеры** → [ARCHITECTURE.md#добавить-новый-storage-адаптер](ARCHITECTURE.md)
- **Новые компоненты** → [FILE_STRUCTURE.md#добавить-новый-компонент](FILE_STRUCTURE.md)
- **Remote Plugins** → [ARCHITECTURE.md#remote-plugins-будущее](ARCHITECTURE.md)

---

## 🗂 Файлы проекта

### Исходный код

#### Ядро (core/)
| Файл | Описание |
|------|----------|
| [core/runtime.py](core/runtime.py) | CoreRuntime — главный координатор |
| [core/event_bus.py](core/event_bus.py) | Шина событий (pub/sub) |
| [core/service_registry.py](core/service_registry.py) | Реестр сервисов (RPC) |
| [core/state_engine.py](core/state_engine.py) | In-memory состояние |
| [core/storage.py](core/storage.py) | Storage API |
| [core/plugin_manager.py](core/plugin_manager.py) | Управление плагинами |

#### Адаптеры (adapters/)
| Файл | Описание |
|------|----------|
| [adapters/storage_adapter.py](adapters/storage_adapter.py) | Абстрактный интерфейс |
| [adapters/sqlite_adapter.py](adapters/sqlite_adapter.py) | SQLite реализация |

#### Плагины (plugins/)
| Файл | Описание |
|------|----------|
| [plugins/base_plugin.py](plugins/base_plugin.py) | Базовый класс плагина |
| [plugins/example_plugin.py](plugins/example_plugin.py) | Пример плагина |

#### Точки входа
| Файл | Описание |
|------|----------|
| [main.py](main.py) | Запуск Runtime |
| [demo.py](demo.py) | Демонстрация |
| [config.py](config.py) | Конфигурация |

### Документация

| Файл | Размер | Описание |
|------|--------|----------|
| [README.md](README.md) | 9.1 KB | Основная документация |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 14 KB | Архитектура |
| [QUICKSTART.md](QUICKSTART.md) | 5.6 KB | Быстрый старт |
| [OVERVIEW.md](OVERVIEW.md) | 8.9 KB | Обзор проекта |
| [FILE_STRUCTURE.md](FILE_STRUCTURE.md) | 9.2 KB | Структура файлов |
| [TODO.md](TODO.md) | 7.0 KB | Roadmap |
| [INDEX.md](INDEX.md) | этот файл | Навигация |

---

## 🎯 Быстрая навигация

### Хочу понять концепцию
→ [README.md](README.md)

### Хочу быстро начать
→ [QUICKSTART.md](QUICKSTART.md)

### Хочу создать плагин
→ [QUICKSTART.md#создание-своего-плагина](QUICKSTART.md)

### Хочу понять архитектуру
→ [ARCHITECTURE.md](ARCHITECTURE.md)

### Хочу увидеть код
→ [demo.py](demo.py) или [plugins/example_plugin.py](plugins/example_plugin.py)

### Хочу найти что-то в коде
→ [FILE_STRUCTURE.md](FILE_STRUCTURE.md)

### Хочу помочь проекту
→ [TODO.md](TODO.md)

---

## 📊 Статистика проекта

| Метрика | Значение |
|---------|----------|
| Строк кода (Python) | 1315 |
| Строк документации | ~2000 |
| Компонентов ядра | 7 |
| Примеров | 2 (demo + example plugin) |
| Зависимостей | 0 (stdlib only) |
| Документов | 7 |

---

## 🔍 Поиск по темам

### A
- **Адаптеры** → [adapters/](adapters/)
- **Архитектура** → [ARCHITECTURE.md](ARCHITECTURE.md)
- **Async/await** → используется везде

### E
- **EventBus** → [core/event_bus.py](core/event_bus.py)
- **Events (события)** → [ARCHITECTURE.md#eventbus](ARCHITECTURE.md)

### P
- **Плагины** → [plugins/](plugins/)
- **PluginManager** → [core/plugin_manager.py](core/plugin_manager.py)
- **Plugin lifecycle** → [README.md#lifecycle-плагина](README.md)

### R
- **Remote plugins** → [ARCHITECTURE.md#remote-plugins-будущее](ARCHITECTURE.md)
- **RPC** → см. ServiceRegistry
- **Runtime** → [core/runtime.py](core/runtime.py)

### S
- **ServiceRegistry** → [core/service_registry.py](core/service_registry.py)
- **StateEngine** → [core/state_engine.py](core/state_engine.py)
- **Storage API** → [core/storage.py](core/storage.py)
- **SQLite** → [adapters/sqlite_adapter.py](adapters/sqlite_adapter.py)

---

## 🎓 Путь обучения

### Уровень 1: Новичок (30 минут)
1. Прочитай [README.md](README.md) — 10 мин
2. Запусти `python3 demo.py` — 5 мин
3. Изучи вывод demo — 5 мин
4. Посмотри [plugins/example_plugin.py](plugins/example_plugin.py) — 10 мин

### Уровень 2: Начинающий разработчик (1 час)
1. Прочитай [QUICKSTART.md](QUICKSTART.md) — 15 мин
2. Создай свой первый плагин — 30 мин
3. Запусти и протестируй — 15 мин

### Уровень 3: Разработчик (2-3 часа)
1. Изучи [ARCHITECTURE.md](ARCHITECTURE.md) — 45 мин
2. Изучи [FILE_STRUCTURE.md](FILE_STRUCTURE.md) — 30 мин
3. Изучи код всех компонентов — 60 мин
4. Напиши сложный плагин — 45 мин

### Уровень 4: Эксперт (неделя)
1. Изучи весь код построчно
2. Напиши свой адаптер
3. Создай несколько плагинов
4. Прочитай [TODO.md](TODO.md) и помоги проекту

---

## 🤝 Участие в проекте

### Как помочь
- **Нашёл баг?** → Создай issue
- **Есть идея?** → Прочитай [TODO.md](TODO.md), создай issue
- **Хочешь код?** → Выбери задачу из [TODO.md](TODO.md), создай PR
- **Улучшение документации?** → Всегда приветствуется!

### Правила
1. Читай документацию перед PR
2. Следуй стилю кода проекта
3. Добавь тесты к своему коду
4. Обнови документацию
5. **Главное правило:** делай ядро МЕНЬШЕ, а не больше

---

## 📞 Получить помощь

### Порядок действий
1. Проверь [README.md](README.md) — возможно, ответ там
2. Проверь [ARCHITECTURE.md](ARCHITECTURE.md) — может быть там
3. Посмотри примеры: [demo.py](demo.py), [example_plugin.py](plugins/example_plugin.py)
4. Создай GitHub Issue с подробным описанием

### Частые вопросы
- **Как создать плагин?** → [QUICKSTART.md#создание-своего-плагина](QUICKSTART.md)
- **Где хранить данные?** → используй Storage API
- **Как общаться с другими плагинами?** → EventBus или ServiceRegistry
- **Где бизнес-логика?** → В плагинах, НЕ в ядре!
- **Почему нет FastAPI?** → Создай плагин api_gateway

---

## 🎯 Следующие шаги

### Для новичков
→ Начни с [README.md](README.md), затем запусти `python3 demo.py`

### Для разработчиков
→ Изучи [ARCHITECTURE.md](ARCHITECTURE.md), создай свой плагин

### Для контрибьюторов
→ Прочитай [TODO.md](TODO.md), выбери задачу, создай PR

---

**Версия:** v0.1.0 (MVP)  
**Дата:** 2026-01-06  
**Статус:** ✅ Ready for use

---

**Навигация:** [↑ Наверх](#-core-runtime-service--индекс-документации)
