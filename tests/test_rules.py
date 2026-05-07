"""Test each rule fires on bad SQL and stays silent on good SQL."""
from pg_migration_safety import lint
from pg_migration_safety.linter import split_statements
from pg_migration_safety.rules import file_level_findings


def codes(sql: str) -> list[str]:
    return [f.rule for f in lint(sql)]


# ---------------------------------------------------------------------------
# R001 -- CREATE INDEX
# ---------------------------------------------------------------------------
def test_r001_fires_without_concurrently():
    assert "R001" in codes("CREATE INDEX idx_users_email ON users(email);")


def test_r001_silent_with_concurrently():
    assert "R001" not in codes(
        "CREATE INDEX CONCURRENTLY idx_users_email ON users(email);"
    )


def test_r001_fires_for_unique_index():
    assert "R001" in codes(
        "CREATE UNIQUE INDEX uniq_users_email ON users(email);"
    )


# ---------------------------------------------------------------------------
# R002 -- ADD COLUMN NOT NULL without DEFAULT
# ---------------------------------------------------------------------------
def test_r002_fires_on_not_null_no_default():
    sql = "ALTER TABLE users ADD COLUMN signed_up_at timestamptz NOT NULL;"
    assert "R002" in codes(sql)


def test_r002_silent_when_default_provided():
    sql = ("ALTER TABLE users ADD COLUMN signed_up_at timestamptz "
           "NOT NULL DEFAULT now();")
    assert "R002" not in codes(sql)


def test_r002_silent_when_nullable():
    sql = "ALTER TABLE users ADD COLUMN nickname text;"
    assert "R002" not in codes(sql)


# ---------------------------------------------------------------------------
# R003 -- ALTER COLUMN TYPE
# ---------------------------------------------------------------------------
def test_r003_fires_on_type_change():
    sql = "ALTER TABLE users ALTER COLUMN id TYPE bigint;"
    assert "R003" in codes(sql)


def test_r003_fires_on_set_data_type():
    sql = "ALTER TABLE users ALTER COLUMN id SET DATA TYPE bigint;"
    assert "R003" in codes(sql)


# ---------------------------------------------------------------------------
# R004 -- RENAME COLUMN
# ---------------------------------------------------------------------------
def test_r004_fires_on_rename_column():
    sql = "ALTER TABLE users RENAME COLUMN nickname TO display_name;"
    assert "R004" in codes(sql)


# ---------------------------------------------------------------------------
# R005 -- ADD CHECK without NOT VALID
# ---------------------------------------------------------------------------
def test_r005_fires_on_check_without_not_valid():
    sql = ("ALTER TABLE users ADD CONSTRAINT users_age_positive "
           "CHECK (age > 0);")
    assert "R005" in codes(sql)


def test_r005_silent_with_not_valid():
    sql = ("ALTER TABLE users ADD CONSTRAINT users_age_positive "
           "CHECK (age > 0) NOT VALID;")
    assert "R005" not in codes(sql)


# ---------------------------------------------------------------------------
# R006 -- ADD FK without NOT VALID
# ---------------------------------------------------------------------------
def test_r006_fires_on_fk_without_not_valid():
    sql = ("ALTER TABLE orders ADD CONSTRAINT orders_user_fk "
           "FOREIGN KEY (user_id) REFERENCES users(id);")
    assert "R006" in codes(sql)


def test_r006_silent_with_not_valid():
    sql = ("ALTER TABLE orders ADD CONSTRAINT orders_user_fk "
           "FOREIGN KEY (user_id) REFERENCES users(id) NOT VALID;")
    assert "R006" not in codes(sql)


# ---------------------------------------------------------------------------
# R007 -- DROP INDEX
# ---------------------------------------------------------------------------
def test_r007_fires_on_drop_index_no_concurrently():
    assert "R007" in codes("DROP INDEX idx_users_email;")


def test_r007_silent_with_concurrently():
    assert "R007" not in codes("DROP INDEX CONCURRENTLY idx_users_email;")


# ---------------------------------------------------------------------------
# R008 -- VACUUM FULL
# ---------------------------------------------------------------------------
def test_r008_fires_on_vacuum_full():
    assert "R008" in codes("VACUUM FULL events;")


def test_r008_silent_on_plain_vacuum():
    assert "R008" not in codes("VACUUM events;")


# ---------------------------------------------------------------------------
# R009 -- DROP COLUMN without IF EXISTS
# ---------------------------------------------------------------------------
def test_r009_fires_on_drop_column_no_if_exists():
    assert "R009" in codes("ALTER TABLE users DROP COLUMN nickname;")


def test_r009_silent_with_if_exists():
    assert "R009" not in codes("ALTER TABLE users DROP COLUMN IF EXISTS nickname;")


# ---------------------------------------------------------------------------
# R010 -- file-level lock_timeout check
# ---------------------------------------------------------------------------
def test_r010_fires_when_ddl_without_lock_timeout():
    sql = "ALTER TABLE users ADD COLUMN nickname text;"
    statements = split_statements(sql)
    found = file_level_findings(sql, statements)
    assert any(f.rule == "R010" for f in found)


def test_r010_silent_when_lock_timeout_set():
    sql = ("SET lock_timeout = '5s';\n"
           "ALTER TABLE users ADD COLUMN nickname text;")
    statements = split_statements(sql)
    found = file_level_findings(sql, statements)
    assert not any(f.rule == "R010" for f in found)


def test_r010_silent_when_no_ddl():
    sql = "SELECT 1;"
    statements = split_statements(sql)
    found = file_level_findings(sql, statements)
    assert not any(f.rule == "R010" for f in found)


# ---------------------------------------------------------------------------
# Splitter / line tracking
# ---------------------------------------------------------------------------
def test_splitter_handles_multiple_statements():
    sql = ("CREATE TABLE a (id int);\n"
           "CREATE TABLE b (id int);\n"
           "CREATE INDEX idx_a ON a(id);")
    statements = split_statements(sql)
    assert len(statements) == 3


def test_splitter_ignores_semicolons_in_strings():
    sql = "INSERT INTO t (s) VALUES ('a;b;c'); CREATE INDEX idx_t ON t(s);"
    statements = split_statements(sql)
    assert len(statements) == 2


def test_splitter_ignores_dollar_quoted_blocks():
    sql = """
DO $$
BEGIN
  PERFORM 1;
  PERFORM 2;
END$$;
CREATE INDEX idx ON t(x);
"""
    statements = split_statements(sql)
    assert len(statements) == 2


def test_findings_carry_line_numbers():
    sql = ("-- header\n"
           "SELECT 1;\n"
           "\n"
           "CREATE INDEX idx_users_email ON users(email);\n")
    findings = lint(sql)
    r001 = [f for f in findings if f.rule == "R001"]
    assert r001 and r001[0].line >= 3


# ---------------------------------------------------------------------------
# Clean migrations should produce zero findings
# ---------------------------------------------------------------------------
def test_clean_migration_produces_no_statement_findings():
    sql = """
SET lock_timeout = '5s';
SET statement_timeout = '60s';

ALTER TABLE users ADD COLUMN signed_up_at timestamptz DEFAULT now();

CREATE INDEX CONCURRENTLY idx_users_signed_up_at ON users(signed_up_at);

ALTER TABLE orders ADD CONSTRAINT orders_user_fk
  FOREIGN KEY (user_id) REFERENCES users(id) NOT VALID;

ALTER TABLE orders VALIDATE CONSTRAINT orders_user_fk;
"""
    findings = lint(sql)
    statements = split_statements(sql)
    findings.extend(file_level_findings(sql, statements))
    assert findings == [], f"Expected no findings, got: {findings}"
