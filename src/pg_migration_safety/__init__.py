"""postgres-migration-safety -- lint Postgres migrations for unsafe patterns."""
from .linter import lint, Finding
from .rules import RULES

__all__ = ["lint", "Finding", "RULES"]
__version__ = "0.1.0"
