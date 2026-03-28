# Core Runtime Service

Execution platform with strict separation:
- `core` — dumb deterministic execution kernel
- `modules` — all business logic (hooks, actions, policies)
- `plugins` — extension layer

For plugin authors, kernel exposes a thin runtime contract (`runtime.api`) to keep plugin code decoupled from internal runtime objects.

## Core Architecture Rules
- Russian core policy (mandatory): [docs/CORE_KERNEL_POLICY_RU.md](docs/CORE_KERNEL_POLICY_RU.md)
- Migration roadmap: [ARCHITECTURE_ROADMAP.md](ARCHITECTURE_ROADMAP.md)
- Cleanup playbook: [PROJECT_CLEANUP_PLAYBOOK.md](PROJECT_CLEANUP_PLAYBOOK.md)

## Local Architecture Guard
```bash
python3 scripts/validate_architecture_rules.py --root .
```
