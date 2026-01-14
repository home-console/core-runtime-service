# ⚙️ Task 002: CI/CD Setup

**Приоритет:** 🔴 КРИТИЧЕСКИЙ  
**Срок:** 4 часа  
**Ответственный:** DevOps  
**Статус:** 🔴 Не начато

---

## 🎯 Цель

Настроить автоматический запуск тестов на каждый push/PR с проверкой coverage.

---

## 📋 Подзадачи

### 1. GitHub Actions Workflow (2 часа)

#### Создать `.github/workflows/tests.yml`:
```yaml
name: Tests

on:
  push:
    branches: [ master, develop ]
  pull_request:
    branches: [ master, develop ]

jobs:
  test-core-runtime:
    name: Core Runtime Tests
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout code
      uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Cache dependencies
      uses: actions/cache@v3
      with:
        path: ~/.cache/pip
        key: ${{ runner.os }}-pip-${{ hashFiles('**/requirements.txt') }}
        restore-keys: |
          ${{ runner.os }}-pip-
    
    - name: Install dependencies
      run: |
        cd core-runtime-service
        pip install -r requirements.txt
        pip install pytest pytest-asyncio pytest-cov
    
    - name: Run tests
      run: |
        cd core-runtime-service
        pytest \
          --cov=core \
          --cov=modules \
          --cov=plugins \
          --cov-report=term-missing \
          --cov-report=xml \
          --cov-report=html \
          --cov-fail-under=80 \
          -v
    
    - name: Upload coverage to Codecov
      uses: codecov/codecov-action@v3
      with:
        file: ./core-runtime-service/coverage.xml
        flags: core-runtime
        name: core-runtime-coverage
    
    - name: Archive coverage HTML report
      uses: actions/upload-artifact@v3
      with:
        name: coverage-report
        path: core-runtime-service/htmlcov/

  test-admin-ui:
    name: Admin UI Tests
    runs-on: ubuntu-latest
    
    steps:
    - name: Checkout code
      uses: actions/checkout@v3
    
    - name: Setup Node.js
      uses: actions/setup-node@v3
      with:
        node-version: '20'
        cache: 'npm'
        cache-dependency-path: admin-ui-service/package-lock.json
    
    - name: Install dependencies
      run: |
        cd admin-ui-service
        npm ci
    
    - name: Run linter
      run: |
        cd admin-ui-service
        npm run lint
    
    - name: Build
      run: |
        cd admin-ui-service
        npm run build
```

### 2. Pre-commit Hooks (1 час)

#### Установить pre-commit:
```bash
pip install pre-commit
```

#### Создать `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-merge-conflict
  
  - repo: https://github.com/psf/black
    rev: 23.12.1
    hooks:
      - id: black
        language_version: python3.11
        files: '^core-runtime-service/'
  
  - repo: https://github.com/charliermarsh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
        files: '^core-runtime-service/'
  
  - repo: local
    hooks:
      - id: pytest-check
        name: pytest-check
        entry: bash -c 'cd core-runtime-service && pytest tests/ -v'
        language: system
        pass_filenames: false
        always_run: true
```

#### Установить hooks:
```bash
pre-commit install
```

### 3. Branch Protection Rules (30 минут)

В GitHub настроить:
- ✅ Require status checks to pass before merging
- ✅ Require branches to be up to date before merging
- ✅ Require tests workflow to pass
- ✅ Require at least 1 approval for PR
- ✅ Dismiss stale pull request approvals

### 4. Coverage Badges (30 минут)

#### Настроить Codecov:
1. Зарегистрироваться на https://codecov.io
2. Подключить репозиторий
3. Получить token

#### Добавить badge в README.md:
```markdown
# HomeConsole

[![Tests](https://github.com/username/HomeConsole/workflows/Tests/badge.svg)](https://github.com/username/HomeConsole/actions)
[![Coverage](https://codecov.io/gh/username/HomeConsole/branch/master/graph/badge.svg)](https://codecov.io/gh/username/HomeConsole)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
```

---

## ✅ Acceptance Criteria

- [ ] GitHub Actions workflow создан
- [ ] Тесты запускаются на каждый push
- [ ] Coverage проверяется (минимум 80%)
- [ ] Pre-commit hooks установлены
- [ ] Branch protection включен
- [ ] Coverage badge добавлен в README
- [ ] Документация обновлена

---

## 🚀 Проверка

### Локально:
```bash
# Проверить pre-commit hooks
pre-commit run --all-files

# Запустить тесты как в CI
cd core-runtime-service
pytest --cov=core --cov=modules --cov-fail-under=80 -v
```

### В GitHub:
1. Создать feature branch
2. Сделать commit
3. Открыть PR
4. Проверить, что workflow запустился
5. Проверить coverage report

---

## 📝 Документация

Обновить `docs/CONTRIBUTING.md`:
```markdown
## Development Workflow

### Running Tests

\`\`\`bash
cd core-runtime-service
pytest -v
\`\`\`

### Coverage

\`\`\`bash
pytest --cov=core --cov=modules --cov-report=html
open htmlcov/index.html
\`\`\`

### Pre-commit Hooks

Pre-commit hooks автоматически запускаются перед каждым commit:
- Code formatting (black)
- Linting (ruff)
- Tests

Установка:
\`\`\`bash
pip install pre-commit
pre-commit install
\`\`\`

### CI/CD

Все PR проходят через CI:
- ✅ Tests must pass
- ✅ Coverage >= 80%
- ✅ Linting must pass
- ✅ Build must succeed

Branch protection требует прохождения всех checks.
```

---

## 🔗 Ссылки

- **Roadmap:** [../ROADMAP.md](../../ROADMAP.md)
- **Testing Strategy:** [../01-testing-strategy.md](../01-testing-strategy.md)
- **GitHub Actions:** https://docs.github.com/en/actions
- **Pre-commit:** https://pre-commit.com/
- **Codecov:** https://codecov.io/

---

## 📊 Прогресс

**Статус:** 🔴 Не начато  
**Затрачено:** 0/4 часов  
**Дата начала:** TBD  
**Дата завершения:** TBD
