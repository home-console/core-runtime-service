from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal


MergeRule = Literal["last_wins", "priority", "deny_override"]


@dataclass(frozen=True)
class ContextPatch:
    data: Mapping[str, Any]
    priority: int = 0
    deny_override: bool = False


def _as_patch(entry: Mapping[str, Any] | ContextPatch) -> ContextPatch:
    if isinstance(entry, ContextPatch):
        return entry
    return ContextPatch(data=entry)


def _deep_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def resolve_context_patches(
    patches: Iterable[Mapping[str, Any] | ContextPatch],
    *,
    rule: MergeRule = "last_wins",
) -> dict[str, Any]:
    patch_items = [_as_patch(patch) for patch in patches if patch is not None]
    if not patch_items:
        return {}

    if rule == "priority":
        ordered = sorted(
            enumerate(patch_items),
            key=lambda item: (item[1].priority, item[0]),
        )
        patch_items = [item[1] for item in ordered]

    merged: dict[str, Any] = {}
    protected_keys: set[str] = set()

    for patch in patch_items:
        for key, value in patch.data.items():
            if rule == "deny_override" and key in protected_keys:
                continue

            existing = merged.get(key)
            if isinstance(existing, dict) and isinstance(value, Mapping):
                merged[key] = _deep_merge(existing, value)
            else:
                merged[key] = value

            if rule == "deny_override" and patch.deny_override:
                protected_keys.add(key)

    return merged