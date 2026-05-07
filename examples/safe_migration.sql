-- Example safe migration. Should produce 0 findings.

SET lock_timeout = '5s';
SET statement_timeout = '60s';

ALTER TABLE users ADD COLUMN signed_up_at timestamptz DEFAULT now();

CREATE INDEX CONCURRENTLY idx_users_signed_up_at ON users(signed_up_at);

ALTER TABLE orders ADD CONSTRAINT orders_user_fk
  FOREIGN KEY (user_id) REFERENCES users(id) NOT VALID;

ALTER TABLE orders VALIDATE CONSTRAINT orders_user_fk;
