"""pgmig CLI -- `pgmig lint <file...>` and exits non-zero on critical findings."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .linter import lint, split_statements
from .rules import file_level_findings


SEV_RANK = {"critical": 0, "warning": 1, "info": 2}
SEV_COLOR = {
    "critical": "\033[31m",  # red
    "warning":  "\033[33m",  # yellow
    "info":     "\033[36m",  # cyan
}
RESET = "\033[0m"


def _format_text(findings, file_path: str, color: bool) -> str:
    if not findings:
        return f"{file_path}: clean -- 0 findings\n"
    lines = [f"{file_path}: {len(findings)} finding(s)"]
    for f in findings:
        prefix = SEV_COLOR[f.severity] if color else ""
        suffix = RESET if color else ""
        lines.append(
            f"  {prefix}[{f.severity.upper()}]{suffix} "
            f"{f.rule} (line {f.line}): {f.message}"
        )
        lines.append(f"    statement: {f.statement!r}")
        lines.append(f"    suggestion: {f.suggestion}")
    return "\n".join(lines) + "\n"


def _format_json(findings, file_path: str) -> str:
    return json.dumps({
        "file": file_path,
        "findings": [f.to_dict() for f in findings],
    }, indent=2) + "\n"


def _process_file(path: Path) -> list:
    sql = path.read_text(encoding="utf-8")
    findings = lint(sql)
    findings.extend(file_level_findings(sql, split_statements(sql)))
    findings.sort(key=lambda f: (f.line, SEV_RANK.get(f.severity, 99)))
    return findings


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="pgmig",
        description="Lint Postgres migrations for unsafe patterns.",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    lint_p = sub.add_parser("lint", help="Lint one or more migration files")
    lint_p.add_argument("files", nargs="+", help="SQL files to check")
    lint_p.add_argument("--format", choices=["text", "json"], default="text")
    lint_p.add_argument("--no-color", action="store_true",
                        help="Disable ANSI color in text output")
    lint_p.add_argument(
        "--fail-on", choices=["critical", "warning", "info"],
        default="critical",
        help="Exit non-zero when any finding meets or exceeds this severity "
             "(default: critical)",
    )

    args = p.parse_args(argv)

    threshold = SEV_RANK[args.fail_on]
    worst_seen = 99
    out_chunks: list[str] = []

    for fname in args.files:
        path = Path(fname)
        if not path.exists():
            print(f"# error: {fname} not found", file=sys.stderr)
            return 2
        findings = _process_file(path)
        if findings:
            worst_seen = min(worst_seen,
                             min(SEV_RANK[f.severity] for f in findings))
        if args.format == "json":
            out_chunks.append(_format_json(findings, str(path)))
        else:
            out_chunks.append(_format_text(findings, str(path),
                                           color=not args.no_color))

    sys.stdout.write("".join(out_chunks))
    return 1 if worst_seen <= threshold else 0


if __name__ == "__main__":
    raise SystemExit(main())
