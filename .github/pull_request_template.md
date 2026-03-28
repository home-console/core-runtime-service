## Summary
- What changed and why.

## Core Kernel Checklist (required)
- [ ] I reviewed [docs/CORE_KERNEL_POLICY_RU.md](docs/CORE_KERNEL_POLICY_RU.md)
- [ ] No new `core -> modules` imports
- [ ] No business decisions in `core` (retry/routing/provider/error interpretation)
- [ ] No derived domain fields in `core/storage`
- [ ] Pipeline behavior remains deterministic and explicit
- [ ] `python3 scripts/validate_architecture_rules.py --root .` has no regression

## Testing
- Commands run:
  - `...`
- Result:
  - `...`
