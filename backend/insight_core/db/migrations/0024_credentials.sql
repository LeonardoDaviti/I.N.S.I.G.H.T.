-- 0024_credentials.sql (Mark IX §10.1)
--
-- Secrets the owner adds in Sources → Connections (the Substack session cookie, the
-- Telegram API id/hash and sign-in session). Values are Fernet-encrypted by the
-- application (ingestion/credentials.py); plaintext is never stored. last4 is the only
-- part of a value the API ever shows. The last_test_* columns hold the provider's latest
-- connection test, copied onto each of its rows.

CREATE TABLE IF NOT EXISTS credentials (
    provider          TEXT        NOT NULL,
    key               TEXT        NOT NULL,
    ciphertext        BYTEA       NOT NULL,
    last4             TEXT,
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_tested_at    TIMESTAMPTZ,
    last_test_ok      BOOLEAN,
    last_test_message TEXT,
    PRIMARY KEY (provider, key)
);
