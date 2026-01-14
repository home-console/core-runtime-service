# 🏠 HomeConsole

Production-ready smart home platform with event-driven plugin architecture.

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 🎯 Overview

HomeConsole — это модульная платформа для управления умным домом с plugin-based архитектурой. Система построена на принципах event-driven design и обеспечивает гибкую интеграцию с различными smart home провайдерами.

### ✨ Ключевые возможности

- ✅ **Event-driven архитектура** — pub/sub через EventBus
- ✅ **Plugin система** — расширяемость без изменения ядра
- ✅ **Модульная структура** — RuntimeModule для инфраструктуры
- ✅ **Authentication & Authorization** — API keys, JWT, Sessions, RBAC
- ✅ **REST API** — полный HTTP API для управления
- ✅ **Web Admin UI** — React интерфейс администратора
- ✅ **Storage API** — key-value с поддержкой SQLite/PostgreSQL
- ✅ **Интеграции** — Yandex Smart Home, OAuth, и другие

---

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Node.js 20+ (для Admin UI)
- SQLite или PostgreSQL

### 1. Core Runtime

```bash
# Clone repository
git clone https://github.com/username/HomeConsole.git
cd HomeConsole/core-runtime-service

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run
python main.py
```

**Core Runtime запущен на http://localhost:8000**

### 2. Admin UI (опционально)

```bash
cd ../admin-ui-service

# Install dependencies
npm install

# Run development server
npm run dev
```

**Admin UI доступен на http://localhost:5173**

---

## 📖 Документация

### Для начинающих
- **[ROADMAP.md](ROADMAP.md)** — План развития проекта 🗺️
- **[Quick Start](#-quick-start)** — Быстрый старт

### Для разработчиков
- **[core-runtime-service/docs/01-ARCHITECTURE.md](core-runtime-service/docs/01-ARCHITECTURE.md)** — Архитектура системы
- **[core-runtime-service/docs/02-MODULES-AND-PLUGINS.md](core-runtime-service/docs/02-MODULES-AND-PLUGINS.md)** — Модули и плагины
- **[core-runtime-service/docs/08-PLUGIN-CONTRACT.md](core-runtime-service/docs/08-PLUGIN-CONTRACT.md)** — Разработка плагинов
- **[roadmap/01-testing-strategy.md](roadmap/01-testing-strategy.md)** — Стратегия тестирования

### Специальные темы
- **[core-runtime-service/docs/auth.md](core-runtime-service/docs/auth.md)** — Аутентификация и авторизация
- **[core-runtime-service/docs/STORAGE_ADAPTERS.md](core-runtime-service/docs/STORAGE_ADAPTERS.md)** — Storage адаптеры

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────┐
│                  Admin UI (React)                   │
│              http://localhost:5173                  │
└─────────────────────────────────────────────────────┘
                         ↓ HTTP/REST
┌─────────────────────────────────────────────────────┐
│              Core Runtime (Python)                  │
│                                                     │
│  ┌──────────────┐  ┌──────────────┐               │
│  │  ApiModule   │  │ AdminModule  │  Modules      │
│  └──────────────┘  └──────────────┘               │
│                                                     │
│  ┌─────────────────────────────────────────┐      │
│  │         EventBus (pub/sub)              │      │
│  │         ServiceRegistry (RPC)           │      │
│  │         Storage (key-value)             │      │
│  │         StateEngine (in-memory)         │      │
│  └─────────────────────────────────────────┘      │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐        │
│  │ Devices  │  │  Yandex  │  │  OAuth   │ Plugins│
│  │ Plugin   │  │  Plugin  │  │  Plugin  │        │
│  └──────────┘  └──────────┘  └──────────┘        │
└─────────────────────────────────────────────────────┘
                         ↓
┌─────────────────────────────────────────────────────┐
│              Storage (SQLite/PostgreSQL)            │
└─────────────────────────────────────────────────────┘
```

### Ключевые компоненты:

- **EventBus** — pub/sub для асинхронного взаимодействия
- **ServiceRegistry** — RPC для синхронных вызовов
- **Storage** — key-value хранилище с адаптерами
- **StateEngine** — in-memory state для быстрого доступа
- **Modules** — инфраструктурные модули (API, Admin)
- **Plugins** — доменные плагины (Devices, Integrations)

---

## 🎯 Roadmap

См. **[ROADMAP.md](ROADMAP.md)** для детального плана развития.

### Ближайшие задачи:

#### 🔴 Фаза 1: Стабилизация (Февраль 2026)
- [ ] Test coverage > 80% ([roadmap/01-testing-strategy.md](roadmap/01-testing-strategy.md))
- [ ] Мониторинг и observability ([roadmap/03-monitoring-observability.md](roadmap/03-monitoring-observability.md))
- [ ] Production-ready deployment

#### 🟡 Фаза 2: Рефакторинг (Март 2026)
- [ ] Консолидация документации ([roadmap/02-documentation-consolidation.md](roadmap/02-documentation-consolidation.md))
- [ ] Разбиение Client Manager на модули
- [ ] Code quality tools

#### 🟠 Фаза 3: Расширение (Апрель-Май 2026)
- [ ] Admin UI — полный функционал
- [ ] Новые интеграции (Telegram, HomeKit, Google Home)
- [ ] Automation Engine v2

---

## 🚦 Текущий статус

### ✅ Работает
- Core Runtime с plugin системой
- API и Admin модули
- Authentication & Authorization
- Devices управление
- Yandex Smart Home интеграция
- Admin UI (базовый)

### 🚧 В разработке
- Тесты (coverage < 30% ⚠️)
- Мониторинг и observability
- Документация (242 файла — требует консолидации)

### 📋 Запланировано
- Test coverage > 80%
- Grafana dashboards
- Telegram интеграция
- Visual automation editor

---

## 🤝 Contributing

Мы приветствуем contributions! См. **[ROADMAP.md](ROADMAP.md)** для списка задач.

### Workflow:

1. Fork репозиторий
2. Создай feature branch (`git checkout -b feature/amazing-feature`)
3. Commit изменения (`git commit -m 'feat: add amazing feature'`)
4. Push в branch (`git push origin feature/amazing-feature`)
5. Открой Pull Request

### Требования к PR:

- ✅ Все тесты проходят
- ✅ Coverage не снижается
- ✅ Code style соблюдён (black/ruff)
- ✅ Документация обновлена

---

## 📊 Проект в цифрах

- **2806** Python файлов
- **16** тестовых файлов (в процессе расширения)
- **7** модулей
- **6+** плагинов
- **242** markdown файла (планируется консолидация до 20)

---

## 📝 License

MIT License - см. [LICENSE](LICENSE) для деталей.

---

## 🔗 Ссылки

- **Roadmap:** [ROADMAP.md](ROADMAP.md)
- **Documentation:** [core-runtime-service/docs/](core-runtime-service/docs/)
- **Python SDK:** [python-sdk/](python-sdk/)
- **Admin UI:** [admin-ui-service/](admin-ui-service/)

---

## ⭐ Star History

Если проект полезен, поставьте ⭐!

---

**🎯 Цель 2026:** Production-ready smart home platform с полным набором интеграций и enterprise features.
