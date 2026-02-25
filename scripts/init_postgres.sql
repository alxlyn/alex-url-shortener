CREATE TABLE IF NOT EXISTS urls (
    code TEXT PRIMARY KEY,
    long_url TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    clicks INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_urls_clicks_code
ON urls (clicks DESC, code ASC);
