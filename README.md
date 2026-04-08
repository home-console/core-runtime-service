# Core Runtime Service

Execution platform with strict separation:
- `core` — dumb deterministic execution kernel
- `modules` — all business logic (hooks, actions, policies)
- `plugins` — extension layer

For plugin authors, kernel exposes the **Plugin SDK** (`sdk.*`) to keep plugin code decoupled from internal runtime objects (no direct `runtime.*` usage in plugins).

## Inspector data surfaces

- **Auth flows**: Inspector endpoint `GET /admin/v1/inspector/auth` returns `{ "auth_flows": [...] }`.
  Source of truth is **storage**: namespace `inspector`, key `auth_flows`.
- **Legacy state**: raw `state` inspector surface was removed. New features should expose
  inspector views via **storage-backed** read-only endpoints instead of dumping `runtime.state`.

## Core Architecture Rules
- Russian core policy (mandatory): [docs/CORE_KERNEL_POLICY_RU.md](docs/CORE_KERNEL_POLICY_RU.md)
- Cleanup playbook: [PROJECT_CLEANUP_PLAYBOOK.md](PROJECT_CLEANUP_PLAYBOOK.md)
- Main core backlog (source of truth): [MAIN_PROBLEMS.md](MAIN_PROBLEMS.md)
- Modules/plugins boundary backlog: [modules_plugins_problems.md](modules_plugins_problems.md)

## Local Architecture Guard
```bash
scripts/py_venv.sh -- scripts/validate_architecture_rules.py --root .
```

## Local Plugin SDK Guard
```bash
python3 scripts/validate_plugin_sdk_imports.py --root .
```

## Local Test Run
```bash
scripts/py_venv.sh -- -m pytest -q
```
