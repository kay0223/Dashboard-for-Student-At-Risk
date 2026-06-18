# At-Risk Student Early-Warning Dashboard

A live **Power BI dashboard**, fed by an automated **Python + Moodle REST API** pipeline, that flags students at academic risk early so educators can intervene before students fall behind.

> Individual industry-experience (internship) project — *Master of Data Science (AI)*, (2026).
> **Tech:** `Python` · `Moodle REST API` · `pandas` · `Power BI` · `ETL` · `star-schema modelling`

---

## Overview

Educators often see that a student is struggling only after grades drop. This project turns raw Moodle activity into an **early-warning system**: it extracts attendance, grade and login-recency signals, scores each student against configurable risk thresholds, and surfaces the results in an interactive Power BI dashboard that refreshes from the same locked data schema each run.

**What it does**

- **Extracts** student, course, grade and engagement data from Moodle via its REST API.
- **Transforms** the raw API JSON into a clean **star schema** (fact + dimension tables) with pure, testable transform functions.
- **Scores risk** per student from attendance, grades and login recency, using thresholds that are easy to tune in one place.
- **Serves** a Power BI dashboard that refreshes simply by re-running the pipeline — the schema is locked, so visuals never break.
- **Degrades gracefully**: a two-layer fallback lets the dashboard run on a realistic demo cohort while real Moodle data is still sparse.

## My role

A solo project completed during an industry-experience internship. I designed and built the **data pipeline and the Power BI dashboard** end to end — the Moodle REST integration, the transform/risk-scoring logic, the star-schema output contract, and the dashboard and its DAX measures.

## Dashboard preview

<!-- Add a screenshot once exported: place it in /docs and update the path below -->
<img width="984" height="567" alt="PAGE 1 EXECUTIVE OVERVIEW" src="https://github.com/user-attachments/assets/794498fb-54ec-4bd8-8503-e5104cc2d07c" />

<img width="963" height="536" alt="PAGE 2  AT-RISK ANALYSIS" src="https://github.com/user-attachments/assets/023c3a33-fa06-4e60-b6fb-946e7d4ebe44" />

<img width="972" height="543" alt="PAGE 3 STUDENT DRILLDOWN" src="https://github.com/user-attachments/assets/5ff91f60-0e4b-4e92-bad7-30aafe8176c8" />

<img width="976" height="556" alt="PAGE 4 ASSESSMENT ANALYSIS" src="https://github.com/user-attachments/assets/7bd2cd92-7ddb-4be8-a743-c075c699ab51" />

> *Screenshot uses the synthetic demo cohort — no real student data is shown.*

---

## Data & privacy

This repository contains **code only** — no real student data and no credentials are committed.

- **No personal data (PII).** The pipeline reads student records (names, IDs, grades, login activity) from Moodle at runtime, but none of it is stored in this repo. The `data/` directory is generated locally and is git-ignored.
- **Demonstrations use mock data.** When real Moodle data is unavailable or a cohort is too small, the pipeline falls back to a **deterministic demo cohort (IDs 1001–1022, "Dummy" names)**. Any sample data shown here is synthetic.
- **Credentials are never committed.** `MOODLE_BASE_URL` and `MOODLE_TOKEN` live in a local `.env` file (git-ignored). Create your own from the Setup section.
- **Built with data governance and responsible/ethical use** of student information in mind.

---

## ETL pipeline

Three notebooks drive the pipeline; both ETL paths emit **identical output schemas**, so the Power BI dashboard works against either without modification.

- **`hybrid_etl.ipynb`** — development phase. Connects to the Moodle sandbox and falls back to mock data per cell when real data is unavailable. Use while real Moodle data is sparse.
- **`production_etl.ipynb`** — production phase. Real Moodle only; fails loud on any missing required field. Use for deployment.
- **`probe_moodle.ipynb`** — diagnostic. Tests every endpoint, prints accessibility, and helps debug token issues.

## Project layout

```
.
├── etl/                       Shared, importable Python package
│   ├── __init__.py
│   ├── schemas.py             Locked column contracts, thresholds, action text
│   ├── moodle_client.py       Moodle REST wrapper + pre-flight check
│   ├── transforms.py          Pure transform functions (API JSON → DataFrames)
│   ├── risk.py                Risk scoring
│   ├── mocks.py               Deterministic mock generators (hybrid only)
│   └── io.py                  Save helpers (CSV + Parquet)
├── hybrid_etl.ipynb           Development entry point (Notebook)
├── production_etl.ipynb       Production entry point (Notebook)
├── probe_moodle.ipynb         Diagnostic notebook (API & endpoints)
├── requirements.txt
├── .gitignore                 Excludes .env and data/ (never commit secrets or PII)
├── .env                       Local only, git-ignored — MOODLE_BASE_URL, MOODLE_TOKEN
└── data/                      Output directory (created on first run, git-ignored)
    ├── raw/                   Raw API responses (JSON)
    ├── processed/             Working dataframes
    └── star_schema/           Power BI source files (the 5 CSVs to upload)
```

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env in the project root (this file is git-ignored — never commit it)
cat > .env <<EOF
MOODLE_BASE_URL=your_base_url_here
MOODLE_TOKEN=your_token_here
EOF

# 3. Sanity-check the token (optional but recommended)
curl "${MOODLE_BASE_URL}/webservice/rest/server.php?wstoken=${MOODLE_TOKEN}&wsfunction=core_webservice_get_site_info&moodlewsrestformat=json"
# "sitename": ...            → token works
# "errorcode":"invalidtoken" → refresh at ${MOODLE_BASE_URL}/admin/tool/webservice/userselect.php

# 4. Open and run a notebook in Jupyter
jupyter notebook hybrid_etl.ipynb
```

---

## How fallback works (hybrid only)

The hybrid pipeline has **two layers of fallback**:

### Layer 1 — Cohort identity
| Real extraction returns... | What happens |
|---|---|
| ≥ `COHORT_THRESHOLD` (default 10) participants | Use real Moodle students with real IDs and names. `data_source = "moodle_*"` |
| < `COHORT_THRESHOLD` participants | Fall back to demo cohort (1001–1022, Dummy). `data_source = "mock_full_cohort_too_small"` |
| API blocked / token invalid / network error | Fall back to demo cohort. `data_source = "mock_full_token_invalid"` (or similar) |

### Layer 2 — Per-cell metric fallback
| Field | Real source | Fallback when missing |
|---|---|---|
| `attendance_pct` | *(none yet — needs Meshed integration)* | Always simulated, deterministic by `(student_id, course_id)` |
| `avg_grade_pct` | `gradereport_user_get_grade_items` | Same deterministic simulator |
| `grade_item_count` | Real count | Simulated 2–5 |
| `days_since_last_login` | `lastaccess` from enrolled-users | BLANK (NaN) when `lastaccess=0` (drives "Never Login" bin); simulated 0–20 if no signal at all |

The simulator is seeded with `(student_id, course_id, base_seed=42)`, so the **same student-course pair always gets the same mocked values** across runs. When real data starts filling in, the rest of the cohort's mocked data doesn't shift.

### `data_source` tracking column
Every row of `fact_student_risk` and `fact_assessment` carries a `data_source` column:

| Value | Meaning |
|---|---|
| `moodle_full` | Student real, grade real, lastaccess real (only attendance is mocked) |
| `moodle_partial` | Student real + lastaccess real, grade mocked |
| `moodle_student_only` | Student real, no grade, no lastaccess |
| `mock_full` | Demo cohort (1001–1022) |
| `mock_full_token_invalid` | Token rejected by Moodle |
| `mock_full_endpoint_blocked` | Token works but endpoint denied |
| `mock_full_network_error` | Connection / timeout |
| `mock_full_cohort_too_small` | Real extraction succeeded but cohort < threshold |

---

## Power BI refresh workflow

Because the schema is locked, refreshing is just re-uploading the same CSVs:

1. Run `hybrid_etl.ipynb` (or `production_etl.ipynb` once real data is available).
2. Confirm the 5 files in `data/star_schema/` are new:
   - `fact_student_risk.csv`
   - `fact_assessment.csv`
   - `dim_student.csv`
   - `dim_course.csv`
   - `dim_assessment.csv`
3. In Power BI, replace each dataset with the new CSV (or `Get Data → CSV` → re-point), then refresh the semantic model.
4. Existing visuals refresh automatically.

**Safe schema changes:** the ETL preserves every existing column name and type. New columns (`data_source`, `role`) load silently and don't appear in any visual until you choose to use them.

**"Never Login" bin:** the ETL emits BLANK for `days_since_last_login` when a student has `lastaccess=0`; the DAX bin uses `IF(ISBLANK(...), "0 - Never Login", ...)`.

---

## Adjusting risk thresholds

Edit `etl/schemas.py`:

```python
# Per-indicator thresholds
ATTENDANCE_HIGH_RISK_BELOW = 70.0
ATTENDANCE_MODERATE_RISK_BELOW = 80.0
GRADE_HIGH_RISK_BELOW = 50.0
GRADE_MODERATE_RISK_BELOW = 65.0
LOGIN_HIGH_RISK_DAYS_ABOVE = 14
LOGIN_MODERATE_RISK_DAYS_ABOVE = 7

# Risk score cutoffs
RISK_HIGH_SCORE = 7    # MAX(risk_score) per student >= 7 → "1 - At Risk"
RISK_MEDIUM_SCORE = 3  # MAX(risk_score) per student >= 3 → "2 - Medium Risk"
```

Any change here requires updating the corresponding DAX measures in Power BI:
`Login Recency Band Display`, `Attendance Band Display`, `Grade Band Display`, and `At Risk Students` (the `>= 7` filter).

---

## Migration to Microsoft Fabric

When the project moves to Fabric notebooks + Lakehouse:

1. Copy the entire `etl/` package and the entry-point notebooks to the Fabric workspace.
2. Replace `etl/io.py` with a Fabric-aware version that writes Delta to the Lakehouse:
   ```python
   def save_dataframe(df, path_no_ext):
       table_name = Path(path_no_ext).name
       (
           spark.createDataFrame(df)
           .write.mode("overwrite").format("delta")
           .saveAsTable(f"lakehouse.dbo.{table_name}")
       )
   ```
3. Inject `MOODLE_TOKEN` from Azure Key Vault into the notebook environment.
4. Schedule `production_etl.ipynb` for daily auto-refresh.
5. Repoint the Power BI semantic model from CSV to the Lakehouse Delta tables.
6. Schema unchanged → dashboard works as-is.

The schema-resistant design means the dashboard never needs to know whether the ETL ran in a local Jupyter notebook or on Fabric against a 50,000-row institutional Moodle.

---

## Troubleshooting

**"Pre-flight FAILED (token_invalid)"** — the Moodle token is rejected. Refresh at `${MOODLE_BASE_URL}/admin/tool/webservice/userselect.php` and update `.env`.

**"Course catalog empty from API"** — token works but `core_course_get_courses` returned nothing. Check the token's user has course access, or check `usercourses` in the site_info response.

**"Real participants extracted: 0"** — token works and courses are found, but `core_enrol_get_enrolled_users` returned no users. The endpoint may be blocked even when others work. Run `probe_moodle.ipynb` to confirm.

**"Real assessment data sparse/empty — using deterministic fallback."** — normal during development; real grade items don't exist for the sandbox cohort yet.

**Power BI refresh fails after running ETL** — usually a column-name mismatch. Verify `fact_student_risk.csv` columns match what Power Query expects, and check the run summary's `data_source_summary` for the mode the ETL ran in.

---

## Author

**Kay Jiang** · [kay0223@gmail.com](mailto:kay0223@gmail.com) · 
Master of Data Science (AI)
