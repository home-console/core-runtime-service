# 📚 Documentation Consolidation — Консолидация документации

**Приоритет:** 🟡 ВЫСОКИЙ  
**Срок:** 3 дня  
**Ответственный:** Tech Lead

---

## 🎯 Цель

Уменьшить количество документации с **242 файлов до 10-15** основных документов, устранить дублирование и создать единую точку входа.

---

## 📊 Текущее состояние

### Проблемы:
- ❌ 242 markdown файла
- ❌ Дублирование информации
- ❌ Устаревшие документы в `docs/archive/`
- ❌ Нет единой точки входа
- ❌ Сложно найти нужную информацию

### Примеры дублирования:
```
docs/00-README.md
docs/01-ARCHITECTURE.md
docs/archive/pre-stabilization/ARCHITECTURE.md
ARCHITECTURE_STABILIZATION.md
QUICK_START.md
docs/03-QUICKSTART.md
```

---

## 📋 План действий

### День 1: Анализ и планирование

#### Шаг 1: Каталогизация (2 часа)
```bash
# Создать список всех MD файлов с метаинформацией
find . -name "*.md" -type f > all_docs.txt

# Анализ дублирования
grep -r "Architecture" --include="*.md" | wc -l
grep -r "Quick Start" --include="*.md" | wc -l
```

#### Шаг 2: Определить структуру (2 часа)
**Целевая структура:**
```
HomeConsole/
├── README.md                    # Главный вход, overview
├── ROADMAP.md                   # Roadmap (уже создан)
├── CHANGELOG.md                 # История изменений
├── CONTRIBUTING.md              # Как контрибьютить
├── docs/
│   ├── README.md                # Навигация по документации
│   ├── ARCHITECTURE.md          # Полная архитектура
│   ├── API_REFERENCE.md         # API справочник
│   ├── PLUGIN_DEVELOPMENT.md    # Разработка плагинов
│   ├── MODULE_DEVELOPMENT.md    # Разработка модулей
│   ├── AUTH_GUIDE.md            # Аутентификация
│   ├── DEPLOYMENT.md            # Деплой и production
│   ├── TESTING.md               # Тестирование
│   ├── TROUBLESHOOTING.md       # Решение проблем
│   └── integrations/            # Интеграции
│       ├── yandex.md
│       ├── homekit.md
│       └── google-home.md
├── core-runtime-service/
│   └── docs/                    # Только технические детали
│       ├── storage-adapters.md
│       └── remote-plugins.md
└── admin-ui-service/
    └── docs/
        └── components.md
```

#### Шаг 3: Создать mapping (1 час)
```markdown
# mapping.md - какие файлы куда мержить

## ARCHITECTURE.md (новый единый файл)
Источники:
- docs/01-ARCHITECTURE.md
- docs/archive/pre-stabilization/ARCHITECTURE.md
- ARCHITECTURE_STABILIZATION.md

## QUICK_START.md → README.md (Quick Start раздел)
Источники:
- QUICK_START.md
- docs/03-QUICKSTART.md

## AUTH_GUIDE.md (новый)
Источники:
- docs/auth.md
- docs/AUTH_ISSUES.md
- DEVICES_PLUGIN_STRICT.md (секция auth)
```

---

### День 2: Консолидация

#### Утро: Создать основные документы (4 часа)

**1. README.md (главный)**
```markdown
# 🏠 HomeConsole

Production-ready smart home platform with plugin architecture.

## 🚀 Quick Start

\`\`\`bash
# 1. Clone repository
git clone https://github.com/username/HomeConsole.git
cd HomeConsole

# 2. Start Core Runtime
cd core-runtime-service
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py

# 3. Start Admin UI
cd ../admin-ui-service
npm install
npm run dev
\`\`\`

## 📖 Documentation

- [Architecture](docs/ARCHITECTURE.md) - System architecture
- [Plugin Development](docs/PLUGIN_DEVELOPMENT.md) - Create plugins
- [API Reference](docs/API_REFERENCE.md) - API documentation
- [Deployment](docs/DEPLOYMENT.md) - Production deployment
- [Roadmap](ROADMAP.md) - Development roadmap

## 🎯 Features

- ✅ Event-driven architecture
- ✅ Plugin system
- ✅ Multiple integrations (Yandex, OAuth)
- ✅ REST API
- ✅ Web admin interface
- ✅ Authentication & authorization

## 🏗️ Architecture

[Diagram and brief overview]

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md)

## 📝 License

MIT
```

**2. docs/ARCHITECTURE.md (единый)**
Объединить:
- Текущее состояние системы
- Core components
- Modules architecture
- Plugin architecture
- Event flow
- Data flow
- Storage architecture
- Security model

**3. docs/PLUGIN_DEVELOPMENT.md**
Объединить:
- Plugin contract
- Base plugin class
- Lifecycle
- Examples
- Best practices
- Testing plugins

#### День: Интеграции и специальные темы (4 часа)

**4. docs/AUTH_GUIDE.md**
```markdown
# Authentication & Authorization Guide

## Overview
HomeConsole uses multi-layer auth:
- API Keys (for service-to-service)
- JWT Tokens (for clients)
- Sessions (for web UI)

## API Keys
[Полная документация]

## JWT Tokens
[Полная документация]

## Sessions
[Полная документация]

## Authorization (ACL)
[Полная документация]

## Examples
[Code examples]
```

**5. docs/DEPLOYMENT.md**
**6. docs/TESTING.md**

---

### День 3: Удаление и финализация

#### Утро: Удаление старых файлов (2 часа)
```bash
# Удалить archive полностью
rm -rf core-runtime-service/docs/archive/

# Удалить дублирующиеся файлы
rm ARCHITECTURE_STABILIZATION.md
rm DEVICES_PLUGIN_FINAL.md
rm DEVICES_PLUGIN_STRICT.md
rm IMPLEMENTATION_COMPLETE.md
rm YANDEX_REAL_IMPLEMENTATION.md

# Удалить старые quickstarts
rm QUICK_START.md

# Переместить специфичные документы в core-runtime-service/docs/
mv docs/STORAGE_ADAPTERS.md core-runtime-service/docs/storage-adapters.md
mv docs/CLIENT_MANAGER_INTEGRATION.md core-runtime-service/docs/client-manager.md
```

#### День: Проверка ссылок (2 часа)
```bash
# Проверить все markdown ссылки
# Использовать markdown-link-check или аналог

npm install -g markdown-link-check
find . -name "*.md" -exec markdown-link-check {} \;

# Исправить все битые ссылки
```

#### Вечер: Финализация (2 часа)
- [ ] Обновить все ссылки в коде
- [ ] Создать docs/README.md с навигацией
- [ ] Добавить table of contents в длинные документы
- [ ] Code review
- [ ] Commit

---

## 🎯 Критерии успеха

### Количественные:
- ✅ Документов: < 20 файлов (было 242)
- ✅ Archive удалён полностью
- ✅ Дублирование устранено (100%)
- ✅ Битых ссылок: 0

### Качественные:
- ✅ Единая точка входа (README.md)
- ✅ Понятная навигация
- ✅ Актуальная информация
- ✅ Примеры кода работают
- ✅ Новичок может начать за 5 минут

---

## 📝 Checklist

### Создать новые документы
- [ ] README.md (обновить)
- [ ] docs/ARCHITECTURE.md
- [ ] docs/API_REFERENCE.md
- [ ] docs/PLUGIN_DEVELOPMENT.md
- [ ] docs/MODULE_DEVELOPMENT.md
- [ ] docs/AUTH_GUIDE.md
- [ ] docs/DEPLOYMENT.md
- [ ] docs/TESTING.md
- [ ] docs/TROUBLESHOOTING.md
- [ ] docs/README.md (навигация)

### Удалить старые
- [ ] docs/archive/ (целиком)
- [ ] ARCHITECTURE_STABILIZATION.md
- [ ] DEVICES_PLUGIN_FINAL.md
- [ ] DEVICES_PLUGIN_STRICT.md
- [ ] IMPLEMENTATION_COMPLETE.md
- [ ] QUICK_START.md
- [ ] YANDEX_REAL_IMPLEMENTATION.md
- [ ] DOCUMENTATION_INDEX.md

### Проверки
- [ ] Все ссылки работают
- [ ] Примеры кода запускаются
- [ ] Table of contents добавлены
- [ ] Грамматика и форматирование
- [ ] Code review passed

---

## 🔗 Ссылки

- **Основной roadmap:** [ROADMAP.md](../ROADMAP.md)
- **Текущая документация:** [docs/](../docs/)
- **Markdown style guide:** https://www.markdownguide.org/

---

## 📊 Прогресс

**Статус:** 🔴 Не начато  
**Файлов сейчас:** 242  
**Файлов цель:** < 20  
**Дата начала:** TBD  
**Дата завершения:** TBD
