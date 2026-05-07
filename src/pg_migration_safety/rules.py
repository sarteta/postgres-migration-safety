"""Rule definitions.

Each rule is a callable that takes a Statement and returns Finding | None.

Rule philosophy: only flag patterns that have caused real production
incidents. False positives are worse than false negatives here -- devs
ignore a noisy linter.

Codes:
  R001  CREATE INDEX without CONCURRENTLY
  R002  ADD COLUMN ... NOT NULL without DEFAULT
  R003  ALTER COLUMN TYPE on existing column (rewrites table)
  R004  RENAME COLUMN (breaks running app)
  R005  ADD CONSTRAINT CHECK without NOT VALID
  R006  ADD FOREIGN KEY without NOT VALID
  R007  DROP INDEX without CONCURRENTLY
  R008  VACUUM FULL (rewrites table)
  R009  DROP COLUMN without IF EXISTS
  R010  Missing lock_timeout / statement_timeout for DDL
"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from .linter import Finding, Statement


def _make_finding(rule: str, severity: str, stmt: "Statement",
                  message: str, suggestion: str) -> "Finding":
    from .linter import Finding
    return Finding(
        rule=rule, severity=severity, line=stmt.start_line,
        statement=stmt.sql[:160],
        message=message, suggestion=suggestion,
    )


# ---------------------------------------------------------------------------
# R001 -- CREATE INDEX without CONCURRENTLY
# ---------------------------------------------------------------------------
_RX_CREATE_INDEX = re.compile(
    r"^\s*CREATE\s+(UNIQUE\s+)?INDEX\b", re.IGNORECASE,
)
_RX_CONCURRENTLY = re.compile(r"\bCONCURRENTLY\b", re.IGNORECASE)


def rule_create_index_concurrently(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_CREATE_INDEX.match(sql):
        return None
    if _RX_CONCURRENTLY.search(sql):
        return None
    return _make_finding(
        "R001", "critical", stmt,
        "CREATE INDEX without CONCURRENTLY locks the table for writes "
        "until the index is built.",
        "Use CREATE INDEX CONCURRENTLY. Note: cannot run inside a "
        "transaction block, and will leave an INVALID index if it fails.",
    )


# ---------------------------------------------------------------------------
# R002 -- ADD COLUMN ... NOT NULL without DEFAULT
# ---------------------------------------------------------------------------
_RX_ADD_COLUMN_NOT_NULL = re.compile(
    r"\bALTER\s+TABLE\b.*\bADD\s+COLUMN\b[^,;]*\bNOT\s+NULL\b",
    re.IGNORECASE | re.DOTALL,
)
_RX_DEFAULT_IN_ADD_COLUMN = re.compile(
    r"\bADD\s+COLUMN\b[^,;]*\bDEFAULT\b",
    re.IGNORECASE | re.DOTALL,
)


def rule_add_column_not_null_no_default(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_ADD_COLUMN_NOT_NULL.search(sql):
        return None
    if _RX_DEFAULT_IN_ADD_COLUMN.search(sql):
        return None
    return _make_finding(
        "R002", "critical", stmt,
        "ADD COLUMN with NOT NULL but no DEFAULT will fail on a "
        "non-empty table.",
        "Either: (a) add the column nullable, backfill in batches, "
        "then SET NOT NULL via a separate migration; or (b) add a "
        "non-volatile DEFAULT in the same statement (Postgres 11+ "
        "applies it without a table rewrite).",
    )


# ---------------------------------------------------------------------------
# R003 -- ALTER COLUMN TYPE
# ---------------------------------------------------------------------------
_RX_ALTER_COLUMN_TYPE = re.compile(
    r"\bALTER\s+TABLE\b.*\bALTER\s+COLUMN\b.*\b(SET\s+DATA\s+)?TYPE\b",
    re.IGNORECASE | re.DOTALL,
)


def rule_alter_column_type(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_ALTER_COLUMN_TYPE.search(sql):
        return None
    return _make_finding(
        "R003", "warning", stmt,
        "ALTER COLUMN TYPE may rewrite the table and holds an "
        "ACCESS EXCLUSIVE lock for the duration.",
        "For large tables: add a new column, backfill in batches, "
        "swap with a rename, then drop the old column. For "
        "compatible types (e.g. varchar(N) -> varchar(M) with M > N) "
        "the rewrite is skipped, but verify on a copy first.",
    )


# ---------------------------------------------------------------------------
# R004 -- RENAME COLUMN
# ---------------------------------------------------------------------------
_RX_RENAME_COLUMN = re.compile(
    r"\bALTER\s+TABLE\b.*\bRENAME\s+COLUMN\b",
    re.IGNORECASE | re.DOTALL,
)


def rule_rename_column(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_RENAME_COLUMN.search(sql):
        return None
    return _make_finding(
        "R004", "warning", stmt,
        "RENAME COLUMN breaks any application instance still running "
        "the old code -- both old and new code cannot coexist.",
        "Multi-step expand/contract: (1) add a new column, (2) "
        "dual-write from the app, (3) backfill, (4) switch reads, "
        "(5) drop old column. RENAME alone forces a hard cut-over.",
    )


# ---------------------------------------------------------------------------
# R005 -- ADD CONSTRAINT CHECK without NOT VALID
# ---------------------------------------------------------------------------
_RX_ADD_CHECK = re.compile(
    r"\bALTER\s+TABLE\b.*\bADD\s+(CONSTRAINT\s+\w+\s+)?CHECK\b",
    re.IGNORECASE | re.DOTALL,
)
_RX_NOT_VALID = re.compile(r"\bNOT\s+VALID\b", re.IGNORECASE)


def rule_add_check_constraint_not_valid(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_ADD_CHECK.search(sql):
        return None
    if _RX_NOT_VALID.search(sql):
        return None
    return _make_finding(
        "R005", "warning", stmt,
        "ADD CONSTRAINT ... CHECK without NOT VALID scans the entire "
        "table while holding an ACCESS EXCLUSIVE lock.",
        "Add the constraint with NOT VALID, then run "
        "ALTER TABLE ... VALIDATE CONSTRAINT in a separate "
        "transaction. VALIDATE only takes a SHARE UPDATE EXCLUSIVE "
        "lock and allows reads/writes.",
    )


# ---------------------------------------------------------------------------
# R006 -- ADD FOREIGN KEY without NOT VALID
# ---------------------------------------------------------------------------
_RX_ADD_FK = re.compile(
    r"\bALTER\s+TABLE\b.*\bADD\s+(CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY\b",
    re.IGNORECASE | re.DOTALL,
)


def rule_add_foreign_key_not_valid(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_ADD_FK.search(sql):
        return None
    if _RX_NOT_VALID.search(sql):
        return None
    return _make_finding(
        "R006", "warning", stmt,
        "ADD FOREIGN KEY without NOT VALID locks both the referencing "
        "and referenced tables while every existing row is checked.",
        "Add the FK with NOT VALID, then VALIDATE CONSTRAINT in a "
        "separate transaction. The validate pass takes only a "
        "SHARE UPDATE EXCLUSIVE lock.",
    )


# ---------------------------------------------------------------------------
# R007 -- DROP INDEX without CONCURRENTLY
# ---------------------------------------------------------------------------
_RX_DROP_INDEX = re.compile(r"^\s*DROP\s+INDEX\b", re.IGNORECASE)


def rule_drop_index_concurrently(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_DROP_INDEX.match(sql):
        return None
    if _RX_CONCURRENTLY.search(sql):
        return None
    return _make_finding(
        "R007", "warning", stmt,
        "DROP INDEX takes an ACCESS EXCLUSIVE lock on the table, "
        "blocking reads and writes.",
        "Use DROP INDEX CONCURRENTLY. Note: cannot run inside a "
        "transaction block.",
    )


# ---------------------------------------------------------------------------
# R008 -- VACUUM FULL
# ---------------------------------------------------------------------------
_RX_VACUUM_FULL = re.compile(r"^\s*VACUUM\s+FULL\b", re.IGNORECASE)


def rule_vacuum_full(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_VACUUM_FULL.match(sql):
        return None
    return _make_finding(
        "R008", "critical", stmt,
        "VACUUM FULL rewrites the entire table and holds an "
        "ACCESS EXCLUSIVE lock for the duration. On a large table "
        "this means hours of downtime.",
        "Use pg_repack or pg_squeeze (online, no exclusive lock). "
        "Reserve VACUUM FULL for maintenance windows on small tables.",
    )


# ---------------------------------------------------------------------------
# R009 -- DROP COLUMN without IF EXISTS (idempotency)
# ---------------------------------------------------------------------------
_RX_DROP_COLUMN = re.compile(
    r"\bALTER\s+TABLE\b.*\bDROP\s+COLUMN\b",
    re.IGNORECASE | re.DOTALL,
)
_RX_DROP_COLUMN_IF_EXISTS = re.compile(
    r"\bDROP\s+COLUMN\s+IF\s+EXISTS\b",
    re.IGNORECASE,
)


def rule_drop_column_if_exists(stmt: "Statement") -> Optional["Finding"]:
    sql = stmt.sql_normalized
    if not _RX_DROP_COLUMN.search(sql):
        return None
    if _RX_DROP_COLUMN_IF_EXISTS.search(sql):
        return None
    return _make_finding(
        "R009", "info", stmt,
        "DROP COLUMN without IF EXISTS fails the migration if a "
        "previous attempt partially succeeded.",
        "Use DROP COLUMN IF EXISTS so the migration is rerunnable.",
    )


# ---------------------------------------------------------------------------
# R010 -- Missing lock_timeout for DDL
# ---------------------------------------------------------------------------
_RX_DDL = re.compile(
    r"^\s*(ALTER|CREATE|DROP)\b", re.IGNORECASE,
)
_RX_LOCK_TIMEOUT = re.compile(
    r"\bSET\s+(LOCAL\s+)?lock_timeout\b", re.IGNORECASE,
)


def rule_lock_timeout_for_ddl_file(_stmt: "Statement") -> Optional["Finding"]:
    """Per-statement rule cannot reasonably check 'file has SET lock_timeout' --
    that is checked at the file level by the CLI, not here."""
    return None


RULES: list[Callable[["Statement"], Optional["Finding"]]] = [
    rule_create_index_concurrently,
    rule_add_column_not_null_no_default,
    rule_alter_column_type,
    rule_rename_column,
    rule_add_check_constraint_not_valid,
    rule_add_foreign_key_not_valid,
    rule_drop_index_concurrently,
    rule_vacuum_full,
    rule_drop_column_if_exists,
]


def file_level_findings(sql: str, statements: list["Statement"]) -> list["Finding"]:
    """File-level checks: e.g. R010 -- DDL present but no lock_timeout SET."""
    from .linter import Finding
    out: list[Finding] = []
    has_ddl = any(_RX_DDL.match(s.sql_normalized) for s in statements)
    has_lock_timeout = bool(_RX_LOCK_TIMEOUT.search(sql))
    if has_ddl and not has_lock_timeout:
        out.append(Finding(
            rule="R010", severity="info",
            line=1, statement="(file)",
            message="No SET lock_timeout in this migration. A DDL "
                    "statement that waits behind a long-running query "
                    "can block all writes to the table indefinitely.",
            suggestion="Start the migration with "
                       "`SET lock_timeout = '5s';` so the migration "
                       "fails fast instead of queueing behind locks.",
        ))
    return out
