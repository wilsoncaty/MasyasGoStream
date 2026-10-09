-- Additive schema: no changes to licenses/sessions or other products' tables.
CREATE TABLE IF NOT EXISTS gostream_licenses (
    id TEXT PRIMARY KEY,
    product_id TEXT NOT NULL CHECK(product_id = 'masyasgostream'),
    code_hash TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'revoked')),
    created_at INTEGER NOT NULL,
    activated_at INTEGER,
    expires_at INTEGER,
    installation_hash TEXT,
    deployment_url TEXT,
    owner_username TEXT,
    password_salt TEXT,
    password_hash TEXT,
    revision INTEGER NOT NULL DEFAULT 0,
    CHECK ((activated_at IS NULL AND expires_at IS NULL) OR
           (activated_at IS NOT NULL AND expires_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS gostream_unique_installation
ON gostream_licenses(product_id, installation_hash) WHERE installation_hash IS NOT NULL;

CREATE TABLE IF NOT EXISTS gostream_sessions (
    token_hash TEXT PRIMARY KEY,
    license_id TEXT NOT NULL REFERENCES gostream_licenses(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS gostream_sessions_expiry ON gostream_sessions(expires_at);
CREATE INDEX IF NOT EXISTS gostream_sessions_license ON gostream_sessions(license_id);

CREATE TABLE IF NOT EXISTS gostream_auth_buckets (
    bucket TEXT PRIMARY KEY,
    window_started_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS gostream_buckets_window ON gostream_auth_buckets(window_started_at);
