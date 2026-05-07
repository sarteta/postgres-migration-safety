-- Example unsafe migration. Every block triggers a rule.

ALTER TABLE users ADD COLUMN signed_up_at timestamptz NOT NULL;

CREATE INDEX idx_users_email ON users(email);

ALTER TABLE users ALTER COLUMN id TYPE bigint;

ALTER TABLE users RENAME COLUMN nickname TO display_name;

ALTER TABLE users ADD CONSTRAINT users_age_positive CHECK (age > 0);

ALTER TABLE orders ADD CONSTRAINT orders_user_fk
  FOREIGN KEY (user_id) REFERENCES users(id);

DROP INDEX idx_users_email;

ALTER TABLE users DROP COLUMN nickname;

VACUUM FULL events;
