-- Logical schema (architecture section 07). CONDITIONAL: fields are mapped only where the real ACABC file has them.
-- PostgreSQL + PostGIS. Raw/identifiable data lives in the restricted schema; the public API reads only `analytics`.

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE SCHEMA IF NOT EXISTS restricted;   -- encrypted storage, steward/ingestion access only
CREATE SCHEMA IF NOT EXISTS analytics;    -- aggregates, benchmarks, policy, audit

-- Required before any private-record ingestion (M0 gate).
CREATE TABLE restricted.dataset_version (
    version_id      text PRIMARY KEY,
    source_url      text NOT NULL,
    licensed_use    text NOT NULL CHECK (length(trim(licensed_use)) > 0),
    rights_authority text NOT NULL,
    acquired_at     timestamptz NOT NULL,
    checksum_sha256 char(64) NOT NULL
);

CREATE TABLE restricted.acabc_fact (
    fact_id           bigserial PRIMARY KEY,
    version_id        text NOT NULL REFERENCES restricted.dataset_version,
    beneficiary_key   char(16),                 -- keyed hash; raw identifiers are never stored
    project_key       char(16),
    enterprise_type   text,
    state_code        text,
    district_code     text,                     -- NULL unless the source has a verified district field
    assistance_amount numeric(16,2),            -- rupees (converted on ingest)
    event_date        date
);
CREATE INDEX ON restricted.acabc_fact (version_id, state_code);

-- Published aggregates: typed, date-versioned, cumulative and FY kept separate.
CREATE TABLE analytics.benchmark_fact (
    benchmark_id   text,
    agency         text NOT NULL,
    source_url     text NOT NULL,
    reference_date date NOT NULL,
    scope          text NOT NULL,               -- e.g. cumulative_since_launch | fy_2026-27_to_date
    metric         text NOT NULL,
    value          numeric NOT NULL,
    unit           text NOT NULL,               -- persons | ventures | schemes | rupees_lakh ...
    PRIMARY KEY (benchmark_id, metric)
);

CREATE TABLE analytics.state_boundary (
    state_code text PRIMARY KEY,
    state_name text NOT NULL UNIQUE,
    geom       geometry(MultiPolygon, 4326)     -- bounded geospatial layer; source and vintage to be recorded
);

CREATE TABLE analytics.policy_document (
    doc_id         text PRIMARY KEY,
    authority      text NOT NULL,
    effective_date date,                        -- NULL = not yet confirmed
    superseded_by  text REFERENCES analytics.policy_document,
    source_url     text NOT NULL,
    operative_verified boolean NOT NULL DEFAULT false,
    indexed_text   text NOT NULL
);

-- No fraud label exists by design.
CREATE TABLE analytics.anomaly_review (
    case_id    text PRIMARY KEY,
    model_ver  text NOT NULL,
    grp        text NOT NULL,
    score      numeric NOT NULL,
    reviewer   text,
    decision   text CHECK (decision IN ('no_action','needs_clarification','escalate_to_programme_official')),
    decided_at timestamptz
);

CREATE TABLE analytics.report_artifact (
    trace_id      text PRIMARY KEY,
    filters       jsonb NOT NULL,
    generated_at  timestamptz NOT NULL,
    artifact_hash char(64) NOT NULL
);

-- Append-only, hash-chained audit trail.
CREATE TABLE analytics.audit_log (
    seq        bigserial PRIMARY KEY,
    ts         timestamptz NOT NULL DEFAULT now(),
    trace_id   text,
    event      text NOT NULL,
    payload    jsonb NOT NULL,
    prev_hash  char(64) NOT NULL,
    hash       char(64) NOT NULL
);
REVOKE UPDATE, DELETE ON analytics.audit_log FROM PUBLIC;
