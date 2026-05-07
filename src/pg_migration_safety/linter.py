"""Top-level lint entrypoint.

Splits SQL into statements (keeping line numbers), runs every rule against
each statement, and returns findings.

The splitter is intentionally simple -- it splits on `;` outside of strings
and dollar-quoted blocks. It is NOT a full SQL parser. Migrations that
embed PL/pgSQL are checked at the statement level only; rule writers
should be aware that they're seeing whole `DO $$ ... $$` blocks as one
statement.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from .rules import RULES


@dataclass
class Finding:
    rule: str
    severity: str           # "critical" | "warning" | "info"
    line: int
    statement: str
    message: str
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Statement:
    sql: str                # original text including whitespace
    start_line: int
    sql_normalized: str = field(default="")  # whitespace-collapsed, lowercase comments stripped

    def __post_init__(self) -> None:
        self.sql_normalized = _normalize(self.sql)


def _normalize(sql: str) -> str:
    """Strip line comments and collapse whitespace for easier matching."""
    out_lines = []
    for raw in sql.split("\n"):
        # strip -- comments
        idx = raw.find("--")
        if idx >= 0:
            raw = raw[:idx]
        out_lines.append(raw)
    text = " ".join(out_lines)
    # collapse internal whitespace
    return " ".join(text.split()).strip()


def split_statements(sql: str) -> list[Statement]:
    """Split SQL on `;` ignoring `;` inside strings and dollar-quoted blocks."""
    statements: list[Statement] = []
    buf: list[str] = []
    line_of_buf_start = 1
    current_line = 1

    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    dollar_tag: str | None = None

    while i < n:
        ch = sql[i]

        if ch == "\n":
            current_line += 1

        if dollar_tag is not None:
            buf.append(ch)
            # look for closing tag
            if sql.startswith(dollar_tag, i):
                buf.extend(sql[i + 1:i + len(dollar_tag)])
                i += len(dollar_tag)
                dollar_tag = None
                continue
            i += 1
            continue

        if in_single:
            buf.append(ch)
            if ch == "'" and not (i + 1 < n and sql[i + 1] == "'"):
                in_single = False
            i += 1
            continue

        if in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
            continue

        # not in any quoted context
        if ch == "'":
            in_single = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_double = True
            buf.append(ch)
            i += 1
            continue

        # dollar quoting: $tag$ ... $tag$ (tag may be empty)
        if ch == "$":
            end = sql.find("$", i + 1)
            if end > i:
                candidate_tag = sql[i:end + 1]
                # only treat as dollar quote if tag chars are valid identifier chars or empty
                inner = candidate_tag[1:-1]
                if all(c.isalnum() or c == "_" for c in inner):
                    dollar_tag = candidate_tag
                    buf.append(candidate_tag)
                    i = end + 1
                    continue

        if ch == ";":
            stmt_text = "".join(buf).strip()
            if stmt_text:
                statements.append(Statement(sql=stmt_text, start_line=line_of_buf_start))
            buf = []
            line_of_buf_start = current_line + (1 if ch == "\n" else 0)
            i += 1
            # skip over any whitespace to align next statement's start line
            while i < n and sql[i] in " \t":
                i += 1
            if i < n and sql[i] == "\n":
                pass  # leave newline tracking to main loop
            continue

        if not buf and ch in " \t\n\r":
            # don't anchor start_line on leading whitespace
            if ch == "\n":
                line_of_buf_start = current_line + 1
            else:
                line_of_buf_start = current_line
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(Statement(sql=tail, start_line=line_of_buf_start))

    return statements


def lint(sql: str) -> list[Finding]:
    """Run every rule against every statement; return findings in order."""
    findings: list[Finding] = []
    for stmt in split_statements(sql):
        for rule in RULES:
            f = rule(stmt)
            if f is not None:
                findings.append(f)
    return findings
