-- ============================================================================
-- Schema for the synthetic bank transaction operations dataset.
-- Dialect: PostgreSQL (works in Postgres / Snowflake with minor tweaks).
-- Load the sample with: COPY transactions FROM 'data/sample_transactions.csv'
--                        WITH (FORMAT csv, HEADER true);
-- ============================================================================

CREATE TABLE IF NOT EXISTS transactions (
    transaction_id        TEXT    NOT NULL,
    txn_date              DATE    NOT NULL,
    account_id            TEXT    NOT NULL,
    transaction_type      TEXT    NOT NULL
        CHECK (transaction_type IN ('ACH','Wire','Check','Card','Zelle/P2P','Bill Pay')),
    channel               TEXT    NOT NULL
        CHECK (channel IN ('Online','Branch','Mobile','ATM','Call Center','API')),
    amount                NUMERIC(14,2) NOT NULL CHECK (amount >= 0),
    status                TEXT    NOT NULL
        CHECK (status IN ('processed','pending','failed','exception')),
    exception_reason      TEXT,
    region                TEXT
        CHECK (region IN ('Northeast','Southeast','Midwest','Southwest','West')),
    processing_time_mins  NUMERIC(8,1) NOT NULL CHECK (processing_time_mins >= 0)
);

CREATE INDEX IF NOT EXISTS idx_txn_date    ON transactions (txn_date);
CREATE INDEX IF NOT EXISTS idx_txn_channel ON transactions (channel);
CREATE INDEX IF NOT EXISTS idx_txn_status  ON transactions (status);
CREATE INDEX IF NOT EXISTS idx_txn_id      ON transactions (transaction_id);
