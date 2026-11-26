# Power BI report: step-by-step

The report reads five views in the PostgreSQL schema `powerbi` (2022 to mid-November 2026) through a read-only login. The `.pbip`
file stays outside the repository: `C:\Users\krish\Documents\MedicalDeviceCopilot.pbip`. Checks: `dashboards/powerbi_scorecard.json`.

## 1. Data files (no database login)

The report loads five CSV files exported from the `powerbi` views: `.venv\Scripts\python -m dashboards.powerbi_export`. They are written to
`data\powerbi\` (git-ignored); their row counts and sha256 are in `dashboards/powerbi_export_manifest.json`. The report cannot reach the database
at all; it is a snapshot, refreshed by re-running the export and then **Refresh** in Power BI. (A read-only database login was the first plan; the
user chose files instead, recorded as an amendment in `dashboards/powerbi_scorecard.json`.)

## 2. Connect

1. Power BI Desktop: **File, Options and settings, Options, Preview features**: tick **Power BI Project (.pbip) save option**. Restart if asked.
2. **Home, Get data, Text/CSV**, open `C:\Users\krish\Documents\Medical-Device-Quality-Copilot\data\powerbi\reports.csv`, **Load**. Repeat for
   `products.csv`, `failure_modes.csv`, `recalls.csv` and `battery_families.csv`.
3. Check the column types in **Transform data** if needed: `date_received`, `quarter_start` and `started` as Date; everything else as Text.
4. **View, Themes, Browse for themes**: `dashboards\powerbi_theme.json`.
5. **File, Save as**, type **Power BI project (.pbip)**: `C:\Users\krish\Documents\MedicalDeviceCopilot.pbip`.

## 3. Model

Relationships (Model view; one-to-many, single direction): `products[product_code]` to `reports[product_code]` and to `recalls[product_code]`;
`failure_modes[failure_mode]` to `reports[failure_mode]`.

Measures (on `reports`, **New measure**):

```
Reports = COUNTROWS ( reports )
Deaths = CALCULATE ( [Reports], reports[event_type] = "Death" )
Battery reports = CALCULATE ( [Reports], reports[failure_mode] = "C_BATTERY" )
Share of reports = DIVIDE ( [Reports], CALCULATE ( [Reports], ALL ( reports[company] ) ) )
Recall records = COUNTROWS ( recalls )
Recall events = DISTINCTCOUNT ( recalls[recall_event] )
Battery family reports = COUNTROWS ( battery_families )
Share in recall families = DIVIDE ( CALCULATE ( COUNTROWS ( battery_families ), battery_families[family] IN { "ACCOLADE", "PROPONENT", "ESSENTIO", "ALTRUA" } ), COUNTROWS ( battery_families ) )
```

Format `Share of reports` and `Share in recall families` as percentages with 1 decimal.

## 4. Pages

Every page gets a small text box at the bottom: *"Report counts are not failure rates. Reports after 2026Q3 are still arriving."*

1. **Overview**: cards for `Reports`, `Deaths`, `Recall records`, `Recall events`; slicer on `products[product]`; clustered column chart of `Reports` by `reports[quarter]`.
2. **Trends and failure modes**: slicer on product; line chart of `Reports` by `quarter`; bar chart of `Reports` by `failure_modes[failure_mode]` (sorted descending); table with `failure_mode`, `definition`, `Reports`.
3. **Companies and recalls**: slicer on product; table with `reports[company]`, `Reports`, `Share of reports` (top 10 by Reports); table of `recalls` (recall_number, company, started, status, reason) sorted by started, descending.
4. **Battery investigation**: page filter product = LWP; line chart of `Battery reports` by `quarter` with legend `company` (filter to BOSTON SCIENTIFIC, ABBOTT); stacked bar of `Battery family reports` by `family` with legend `period`; card `Share in recall families` filtered to period 2025Q4-2026Q3; text box: *"A recall for the ACCOLADE family started on 2025-08-20. Timing and device families line up with the jump; the data cannot show that the recall caused the reports."*

## 5. Evidence

1. For each visual listed in `dashboards/powerbi_exports.json` (written by `python -m dashboards.verify_powerbi --list`): **More options (...), Export data, Summarized data, .csv**, saved under `docs\figures\powerbi\exports\` with the given file name.
2. **File, Export, Export to PDF**: `docs\figures\powerbi\MedicalDeviceCopilot.pdf`.
3. A PNG of each page (Windows + Shift + S) as `docs\figures\powerbi\page1.png` to `page4.png`.

Then: `.venv\Scripts\python -m dashboards.verify_powerbi`.
