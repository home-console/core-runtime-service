# Storage адаптеры

Core Runtime поддерживает несколько типов storage адаптеров для хранения данных.

## Доступные адаптеры

### SQLite (по умолчанию)

Простой файловый адаптер, не требует дополнительных зависимостей.

**Использование:**
```bash
export RUNTIME_STORAGE_TYPE=sqlite
export RUNTIME_DB_PATH=data/runtime.db
python main.py
```

### PostgreSQL

Асинхронный адаптер для PostgreSQL через `asyncpg`.

**Требования:**
```bash
pip install asyncpg
```

**Использование:**
```bash
export RUNTIME_STORAGE_TYPE=postgresql
export RUNTIME_PG_HOST=localhost
export RUNTIME_PG_PORT=5432
export RUNTIME_PG_DATABASE=homeconsole
export RUNTIME_PG_USER=postgres
export RUNTIME_PG_PASSWORD=your_password
python main.py
```

Или через DSN:
```bash
export RUNTIME_STORAGE_TYPE=postgresql
export RUNTIME_PG_DSN=postgresql://user:password@host:port/database
python main.py
```

## Переменные окружения

### Общие
- `RUNTIME_STORAGE_TYPE` - тип адаптера: `sqlite` или `postgresql` (по умолчанию: `sqlite`)

### SQLite
- `RUNTIME_DB_PATH` - путь к файлу БД (по умолчанию: `data/runtime.db`)

### PostgreSQL
- `RUNTIME_PG_HOST` - хост PostgreSQL (по умолчанию: `localhost`)
- `RUNTIME_PG_PORT` - порт PostgreSQL (по умолчанию: `5432`)
- `RUNTIME_PG_DATABASE` - имя базы данных (по умолчанию: `homeconsole`)
- `RUNTIME_PG_USER` - пользователь (по умолчанию: `postgres`)
- `RUNTIME_PG_PASSWORD` - пароль (по умолчанию: пустая строка)
- `RUNTIME_PG_DSN` - строка подключения (если указана, остальные `RUNTIME_PG_*` игнорируются)

## Схема данных

Оба адаптера используют одинаковую схему:

```sql
CREATE TABLE storage (
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (namespace, key)
);
```

Значения хранятся в формате JSON (TEXT).

## Миграция между адаптерами

Данные совместимы между адаптерами, так как используется одинаковая схема.
Для миграции можно экспортировать данные из одного адаптера и импортировать в другой.
