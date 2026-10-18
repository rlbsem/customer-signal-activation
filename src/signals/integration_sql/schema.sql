CREATE TABLE IF NOT EXISTS CSA_ACCOUNTS (
    source_ref VARCHAR NOT NULL,
    source_modified_at VARCHAR NOT NULL,
    brand VARCHAR NOT NULL,
    account_key VARCHAR NOT NULL,
    owner_key VARCHAR NOT NULL,
    owner_ref VARCHAR NOT NULL,
    active BOOLEAN NOT NULL,
    synthetic BOOLEAN NOT NULL
);
CREATE TABLE IF NOT EXISTS CSA_REVIEWS (
    source_ref VARCHAR NOT NULL,
    source_modified_at VARCHAR NOT NULL,
    account_source_ref VARCHAR NOT NULL,
    action_key VARCHAR NOT NULL,
    review_status VARCHAR NOT NULL,
    proposed_action VARCHAR NOT NULL
);
CREATE TABLE IF NOT EXISTS CSA_INGESTION (
    run_id VARCHAR NOT NULL,
    observed_at VARCHAR NOT NULL,
    input_hash VARCHAR NOT NULL,
    account_versions BIGINT NOT NULL,
    review_versions BIGINT NOT NULL
);
