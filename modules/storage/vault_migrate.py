"""
Vault backend migration — copy vault storage data between backends
(SQLite <-> PostgreSQL), in either direction.

Unlike `modules.storage.migrate` (single-mode → dual-mode, within one backend),
this tool moves the *vault* storage of an already-dual-mode deployment from one
backend to another, e.g. when switching `RUNTIME_VAULT_STORAGE_TYPE` from
`sqlite` to `postgresql` (or back).

Works standalone (no running Config/runtime required) — both source and target
adapters are built directly from CLI args, so it can be used in dev (via
`hc env vault migrate`) and in production the same way.

Usage:
    python -m modules.storage.vault_migrate \\
        --from sqlite --from-path data/vault.db \\
        --to postgres --to-dsn "postgresql://vault:***@postgres:5432/homeconsole?options=-csearch_path%3Dvault"

    # dry run, only show what would be copied
    python -m modules.storage.vault_migrate ... --dry-run

    # delete source records after a verified copy (use with care)
    python -m modules.storage.vault_migrate ... --delete-source
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from core.adapters.storage_adapter import StorageAdapter

logger = logging.getLogger(__name__)


def build_adapter(kind: str, *, db_path: str | None = None, dsn: str | None = None) -> StorageAdapter:
    """Construct a standalone StorageAdapter (sqlite or postgresql)."""
    kind = kind.strip().lower()
    if kind == "sqlite":
        if not db_path:
            raise ValueError("db_path required for sqlite adapter")
        from core.adapters.sqlite_adapter import SQLiteAdapter

        return SQLiteAdapter(db_path)

    if kind in ("postgres", "postgresql"):
        if not dsn:
            raise ValueError("dsn required for postgresql adapter")
        from core.adapters.postgresql_adapter import PostgreSQLAdapter

        return PostgreSQLAdapter(dsn=dsn)

    raise ValueError(f"Unknown storage kind: {kind!r}; must be 'sqlite' or 'postgresql'")


async def migrate_storage(
    source: StorageAdapter,
    target: StorageAdapter,
    *,
    namespaces: list[str] | None = None,
    delete_source: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    """
    Copy all (or selected) namespaces from `source` to `target`.

    Returns a dict mapping namespace -> number of records copied.
    Does not close either adapter — caller is responsible for that.
    """
    await target.initialize_schema()

    all_namespaces = await source.list_namespaces()
    selected = (
        [ns for ns in all_namespaces if ns in set(namespaces)]
        if namespaces
        else all_namespaces
    )

    results: dict[str, int] = {}
    for ns in selected:
        keys = await source.list_keys(ns)
        if dry_run:
            results[ns] = len(keys)
            logger.info(f"[dry-run] {ns}: {len(keys)} record(s) would be copied")
            continue

        copied = 0
        for key in keys:
            value = await source.get(ns, key)
            if value is not None:
                await target.set(ns, key, value)
                copied += 1
        results[ns] = copied
        logger.info(f"{ns}: copied {copied}/{len(keys)} record(s)")

        if delete_source:
            target_keys = set(await target.list_keys(ns))
            if not set(keys).issubset(target_keys):
                raise RuntimeError(
                    f"Refusing to delete source namespace '{ns}': "
                    f"not all keys verified in target"
                )
            for key in keys:
                await source.delete(ns, key)
            logger.info(f"{ns}: deleted {len(keys)} record(s) from source")

    return results


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate vault storage between backends")
    parser.add_argument("--from", dest="from_kind", required=True, choices=["sqlite", "postgres", "postgresql"])
    parser.add_argument("--from-path", dest="from_path", help="SQLite path for source")
    parser.add_argument("--from-dsn", dest="from_dsn", help="PostgreSQL DSN for source")
    parser.add_argument("--to", dest="to_kind", required=True, choices=["sqlite", "postgres", "postgresql"])
    parser.add_argument("--to-path", dest="to_path", help="SQLite path for target")
    parser.add_argument("--to-dsn", dest="to_dsn", help="PostgreSQL DSN for target")
    parser.add_argument("--namespace", dest="namespaces", action="append", help="Limit to namespace (repeatable)")
    parser.add_argument("--delete-source", action="store_true", help="Delete records from source after verified copy")
    parser.add_argument("--dry-run", action="store_true", help="Only report what would be copied")
    return parser.parse_args(argv)


async def _main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    args = _parse_args(argv)

    source = build_adapter(args.from_kind, db_path=args.from_path, dsn=args.from_dsn)
    target = build_adapter(args.to_kind, db_path=args.to_path, dsn=args.to_dsn)

    try:
        results = await migrate_storage(
            source,
            target,
            namespaces=args.namespaces,
            delete_source=args.delete_source,
            dry_run=args.dry_run,
        )
    finally:
        await source.close()
        await target.close()

    total = sum(results.values())
    logger.info(f"Done: {total} record(s) across {len(results)} namespace(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main(sys.argv[1:])))
