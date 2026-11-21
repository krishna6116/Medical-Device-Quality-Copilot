-- Phase 2 schema (star schema around two facts: reports and recalls).
-- Recreated by mdqc.load on every run, so the load is idempotent. Schema name is a placeholder
-- ({schema}) so the verifier can load planted-fault copies into a separate schema.

DROP SCHEMA IF EXISTS {schema} CASCADE;
CREATE SCHEMA {schema};
SET search_path TO {schema};

-- Dimensions -------------------------------------------------------------------------------
CREATE TABLE dim_product_code (
    product_code        text PRIMARY KEY,
    device_name         text NOT NULL,
    device_class        text,
    medical_specialty   text,
    regulation_number   text,
    family              text NOT NULL          -- from config/scope.json (orthopedic / cardiac / diabetes)
);

CREATE TABLE dim_manufacturer (
    manufacturer_id     integer PRIMARY KEY,
    raw_name            text NOT NULL UNIQUE,  -- exactly as FDA wrote it ('' allowed)
    clean_name          text NOT NULL,         -- upper-case, punctuation and legal suffixes removed
    parent_company      text NOT NULL          -- config/manufacturer_aliases.json
);

CREATE TABLE dim_date (
    date_value          date PRIMARY KEY,
    year                smallint NOT NULL,
    quarter             smallint NOT NULL,
    month               smallint NOT NULL,
    month_start         date NOT NULL
);

-- Report fact and its children ---------------------------------------------------------------
CREATE TABLE fact_report (
    mdr_report_key      text PRIMARY KEY,
    report_number       text,
    product_code        text NOT NULL REFERENCES dim_product_code,
    manufacturer_id     integer NOT NULL REFERENCES dim_manufacturer,
    date_received       date NOT NULL REFERENCES dim_date,
    date_of_event       date,
    event_date_flag     text NOT NULL CHECK (event_date_flag IN ('ok', 'missing', 'invalid', 'after_received')),
    lag_days            integer,               -- date_received - date_of_event when both valid
    event_type          text NOT NULL CHECK (event_type IN ('Malfunction', 'Injury', 'Death', 'Other', 'Not provided')),
    report_source_code  text,
    type_of_report      text,                  -- e.g. Initial submission / Followup, joined with '; '
    pma_pmn_number      text,                  -- 510(k) (K...), PMA (P...), De Novo (DEN...) number or NULL
    brand_name          text,                  -- from the first device entry with the scope code
    generic_name        text,
    model_number        text,
    lot_number          text,
    n_devices           smallint NOT NULL,
    n_patients          smallint NOT NULL,
    adverse_event_flag  text,
    product_problem_flag text
);
CREATE INDEX ON fact_report (product_code, date_received);
CREATE INDEX ON fact_report (manufacturer_id);
CREATE INDEX ON fact_report (pma_pmn_number);

CREATE TABLE report_device (
    mdr_report_key      text NOT NULL REFERENCES fact_report ON DELETE CASCADE,
    device_seq          smallint NOT NULL,     -- position in the report's device list (1-based)
    product_code        text,
    brand_name          text,
    generic_name        text,
    manufacturer_raw    text,
    model_number        text,
    catalog_number      text,
    lot_number          text,
    implant_flag        text,
    PRIMARY KEY (mdr_report_key, device_seq)
);

CREATE TABLE report_problem (               -- FDA device problem terms, once per report
    mdr_report_key      text NOT NULL REFERENCES fact_report ON DELETE CASCADE,
    term                text NOT NULL,
    PRIMARY KEY (mdr_report_key, term)
);

CREATE TABLE report_patient_problem (       -- FDA patient problem terms only (no demographics)
    mdr_report_key      text NOT NULL REFERENCES fact_report ON DELETE CASCADE,
    term                text NOT NULL,
    PRIMARY KEY (mdr_report_key, term)
);

CREATE TABLE report_text (
    mdr_report_key      text NOT NULL REFERENCES fact_report ON DELETE CASCADE,
    text_seq            smallint NOT NULL,     -- position in mdr_text (1-based)
    text_type           text,                  -- 'Description of Event or Problem' / 'Additional Manufacturer Narrative'
    text                text NOT NULL,
    PRIMARY KEY (mdr_report_key, text_seq)
);

-- Recall fact and links ----------------------------------------------------------------------
CREATE TABLE fact_recall (
    product_res_number  text PRIMARY KEY,
    res_event_number    text,
    product_code        text NOT NULL REFERENCES dim_product_code,
    recalling_firm      text,
    manufacturer_id     integer NOT NULL REFERENCES dim_manufacturer,
    recall_status       text,
    event_date_initiated date NOT NULL,
    initiated_date_repaired boolean NOT NULL,
    event_date_posted   date,
    event_date_terminated date,
    root_cause          text,
    reason_for_recall   text,
    action              text,
    product_description text,
    product_quantity    text,
    k_numbers           text[] NOT NULL,
    code_info           text                   -- cut to 2,000 characters at download
);

CREATE TABLE report_recall_link (
    mdr_report_key      text NOT NULL REFERENCES fact_report ON DELETE CASCADE,
    product_res_number  text NOT NULL REFERENCES fact_recall ON DELETE CASCADE,
    link_type           text NOT NULL CHECK (link_type IN ('510k', 'firm_window')),
    days_from_initiation integer NOT NULL,     -- date_received - recall initiation date
    PRIMARY KEY (mdr_report_key, product_res_number, link_type)
);
CREATE INDEX ON report_recall_link (product_res_number);

-- Bookkeeping ----------------------------------------------------------------------------------
CREATE TABLE quarantine (
    source              text NOT NULL,         -- file name
    record_key          text,
    rule                text NOT NULL,         -- R1-R5 / Q1-Q2 (config/phase2_criteria.json)
    detail              text NOT NULL,
    raw                 jsonb NOT NULL         -- the record as downloaded, minus never-loaded personal fields
);

CREATE TABLE load_run (
    run_id              text PRIMARY KEY,
    started_utc         timestamptz NOT NULL,
    finished_utc        timestamptz NOT NULL,
    raw_checksums       jsonb NOT NULL,
    counts              jsonb NOT NULL
);
