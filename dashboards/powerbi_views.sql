-- Phase 8 part 2: views for the Power BI report (schema powerbi, owned by the app login, read by mdqc_powerbi_ro).
-- Applied by python -m dashboards.powerbi_setup --views. Read-only views over core_all / analytics_all (2022 to mid-November 2026).
DROP SCHEMA IF EXISTS powerbi CASCADE;
CREATE SCHEMA powerbi;

CREATE VIEW powerbi.products AS
SELECT product_code, device_name, family,
       CASE product_code WHEN 'LPH' THEN 'Hip implant, uncemented' WHEN 'JWH' THEN 'Knee implant, cemented' WHEN 'MBH' THEN 'Knee implant, uncemented'
                         WHEN 'LWP' THEN 'Pacemaker' WHEN 'LZG' THEN 'Insulin pump' END AS product
FROM core_all.dim_product_code;

-- One row per report: the fact table of the model
CREATE VIEW powerbi.reports AS
SELECT r.mdr_report_key, r.product_code, r.date_received, date_trunc('quarter', r.date_received)::date AS quarter_start,
       to_char(r.date_received, 'YYYY"Q"Q') AS quarter, r.event_type, m.parent_company AS company, f.mode AS failure_mode,
       (r.date_received > '2026-09-30') AS incomplete_period
FROM core_all.fact_report r
JOIN core_all.dim_manufacturer m USING (manufacturer_id)
JOIN analytics_all.report_failure_mode f USING (mdr_report_key);

-- powerbi.failure_modes (code and definition) is created by powerbi_setup from config/failure_modes.json

CREATE VIEW powerbi.recalls AS
SELECT c.product_res_number AS recall_number, c.res_event_number AS recall_event, c.product_code, m.parent_company AS company,
       c.event_date_initiated AS started, c.recall_status AS status, c.root_cause, left(regexp_replace(c.reason_for_recall, '\s+', ' ', 'g'), 300) AS reason
FROM core_all.fact_recall c JOIN core_all.dim_manufacturer m USING (manufacturer_id);

-- Boston Scientific pacemaker battery reports by device family (the app's guided investigation)
CREATE VIEW powerbi.battery_families AS
SELECT r.mdr_report_key, to_char(r.date_received, 'YYYY"Q"Q') AS quarter,
       CASE WHEN r.date_received <= '2025-09-30' THEN '2025Q1-2025Q3' ELSE '2025Q4-2026Q3' END AS period,
       COALESCE((SELECT w FROM regexp_split_to_table(regexp_replace(upper(COALESCE(r.brand_name, '')), '[^A-Z]+', ' ', 'g'), ' ') AS w
                 WHERE w IN ('ACCOLADE', 'PROPONENT', 'ESSENTIO', 'ALTRUA', 'VITALIO', 'INGENIO', 'FORMIO', 'ADVANTIO') LIMIT 1), 'OTHER') AS family
FROM core_all.fact_report r
JOIN core_all.dim_manufacturer m USING (manufacturer_id)
JOIN analytics_all.report_failure_mode f USING (mdr_report_key)
WHERE r.product_code = 'LWP' AND f.mode = 'C_BATTERY' AND m.parent_company = 'BOSTON SCIENTIFIC' AND r.date_received BETWEEN '2025-01-01' AND '2026-09-30';
