# postgres-migration-safety

[![tests](https://github.com/sarteta/postgres-migration-safety/actions/workflows/tests.yml/badge.svg)](https://github.com/sarteta/postgres-migration-safety/actions/workflows/tests.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) ![Python](https://img.shields.io/badge/python-3.10%2B-blue)

A linter for Postgres schema migrations. Reads a `.sql` file, flags the
patterns that lock tables, rewrite tables, or break running app instances.

## Install

```bash
pip install postgres-migration-safety
```

## Run

```bash
pgmig lint migrations/0042_add_signup_timestamp.sql
```

```bash
# fail the build on warnings too
pgmig lint db/migrations/*.sql --fail-on warning

# JSON output for CI / pre-commit
pgmig lint migrations/*.sql --format json
```

## Rules

| Code | Severity | Pattern | Safe alternative the rule suggests |
|---|---|---|---|
| `R001` | critical | `CREATE INDEX` without `CONCURRENTLY` | `CREATE INDEX CONCURRENTLY` |
| `R002` | critical | `ADD COLUMN ... NOT NULL` with no `DEFAULT` | nullable + backfill, then `SET NOT NULL` |
| `R003` | warning | `ALTER COLUMN TYPE` | new column + backfill + swap |
| `R004` | warning | `RENAME COLUMN` | expand/contract: dual-write + backfill |
| `R005` | warning | `ADD CHECK` without `NOT VALID` | `NOT VALID` then `VALIDATE CONSTRAINT` |
| `R006` | warning | `ADD FOREIGN KEY` without `NOT VALID` | `NOT VALID` then `VALIDATE CONSTRAINT` |
| `R007` | warning | `DROP INDEX` without `CONCURRENTLY` | `DROP INDEX CONCURRENTLY` |
| `R008` | critical | `VACUUM FULL` | `pg_repack` / `pg_squeeze` |
| `R009` | info | `DROP COLUMN` without `IF EXISTS` | add `IF EXISTS` for rerunnability |
| `R010` | info | DDL with no `SET lock_timeout` | start file with `SET lock_timeout = '5s';` |

## Example output

```
$ pgmig lint examples/unsafe_migration.sql

examples/unsafe_migration.sql: 9 finding(s)
  [CRITICAL] R002 (line 3): ADD COLUMN with NOT NULL but no DEFAULT will
    fail on a non-empty table.
    suggestion: Either (a) add the column nullable, backfill in batches,
    then SET NOT NULL via a separate migration; or (b) add a non-volatile
    DEFAULT in the same statement (Postgres 11+ applies it without a
    table rewrite).
  [CRITICAL] R001 (line 5): CREATE INDEX without CONCURRENTLY locks the
    table for writes until the index is built.
    suggestion: Use CREATE INDEX CONCURRENTLY. Cannot run inside a
    transaction block.
  ...
```

## Exit codes

| Exit | Meaning |
|---|---|
| 0 | No findings at or above `--fail-on` (default `critical`) |
| 1 | At least one finding meets the threshold |
| 2 | File not found |

## CI snippet

```yaml
- name: Lint migrations
  run: |
    pip install postgres-migration-safety
    pgmig lint db/migrations/*.sql --fail-on warning
```

## Caveats

The splitter is regex-based, not a real Postgres parser. PL/pgSQL inside
`DO $$ ... $$` blocks is treated as one statement. Rules are pattern
matchers, so `ALTER COLUMN TYPE` on a 5-row config table still warns
even though the rewrite is harmless. Drop the noisy rule from CI for
the file or split big migrations across several files.

## Related

- [`postgres-incident-toolkit`](https://github.com/sarteta/postgres-incident-toolkit) -- detect long queries, lock waits, replication lag
- [`postgres-tuning-cookbook`](https://github.com/sarteta/postgres-tuning-cookbook) -- tuning patterns ranked by impact
- [`postgres-production-playbook`](https://github.com/sarteta/postgres-production-playbook) -- diagnostic SQL keyed to symptom
- [`mcp-postgres-doctor`](https://github.com/sarteta/mcp-postgres-doctor) -- same scanners over MCP

MIT (c) 2026 Santiago Arteta
