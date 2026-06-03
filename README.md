# Dashboard-for-Student-At-Risk
Live PowerBI dashboard to monitor at-risk students using Moodle data via REST API 
# At-Risk Student Dashboard — ETL

Two-script ETL for the Moodle-fed at-risk student dashboard.

- **`hybrid_etl.ipynb`** — development phase. Connects to the Moodle sandbox, falls back to mock data per cell when real data is unavailable. Use this Notebook while real Moodle data is sparse.
- **`production_etl.ipynb`** — production phase. Real Moodle only. Fails loud on any missing required field.  Use this Notebook for deployment.
- **`probe_moodle.ipynb`** — diagnostic. Tests every endpoint, prints accessibility, helps debug token issues.

Both pipelines produce **identical output schemas** so the Power BI dashboard works against either one without modification.

---

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
├── probe_moodle.ipynb         Diagnostic notebook (API & Endpoints)
├── requirements.txt
├── .env                       (Store) MOODLE_BASE_URL, MOODLE_TOKEN 
└── ../data/                   Output directory (created on first run)
    ├── raw/                   Raw API responses (JSON)
    ├── processed/             Working dataframes
    └── star_schema/           Power BI source files (the 5 CSVs to upload)
```

---

## Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Create .env in the project root or one level up
cat > .env <<EOF
MOODLE_BASE_URL=https://spi.nsw.edu.au/learn
MOODLE_TOKEN=<4daf5db24f615a924be6299b5e3ba4ec>
EOF

# 3. Sanity-check the token (optional but recommended)
curl "${MOODLE_BASE_URL}/webservice/rest/server.php?wstoken=${MOODLE_TOKEN}&wsfunction=core_webservice_get_site_info&moodlewsrestformat=json"
# If you see "sitename": ... → token works
# If you see "errorcode":"invalidtoken" → refresh the token at:
#   ${MOODLE_BASE_URL}/admin/tool/webservice/userselect.php

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

### `data_source` Tracking column
Every row of `fact_student_risk` and `fact_assessment` has a `data_source` column:

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

1. Run `hybrid_etl.ipynb` (or `production_etl.ipynb` once Real Data is available and Fabric is ready)
2. Confirm the 5 files in `data/star_schema/` are new:
   - `fact_student_risk.csv`
   - `fact_assessment.csv` 
   - `dim_student.csv`
   - `dim_course.csv`
   - `dim_assessment.csv` 
3. In Power BI Web, replace each dataset with the new CSV in SPI OneDriver Folder  (or use `Get Data → CSV` → re-point), then refresh in the PowerBI semantic model 
4. Existing visuals refresh automatically

**Safe schema changes:** the unified ETL preserves every existing column name and type. New columns (`data_source`, `role`) load silently and don't appear in any visual until choose to use them.

**Heads-up on the "Never Login" bin:** the unified ETL emits BLANK (empty cell) for `days_since_last_login` when a student has `lastaccess=0`. The DAX bin definition used `IF(ISBLANK(...), "0 - Never Login", ...)`.

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
RISK_HIGH_SCORE = 7   # MAX(risk_score) per student >= 7 → "1 - At Risk"
RISK_MEDIUM_SCORE = 3 # MAX(risk_score) per student >= 3 → "2 - Medium Risk"
```

Any change here requires updating the corresponding DAX measures in Power BI:
- `Login Recency Band Display` (the `<=` bin breakpoints)
- `Attendance Band Display`
- `Grade Band Display`
- `At Risk Students` (the `>= 7` filter)

---

## Migration to Microsoft Fabric

When the project moves to Fabric notebooks + Lakehouse:

1. Copy the entire `etl/` package and the entry-point notebooks to the Fabric workspace
2. Replace `etl/io.py` with a Fabric-aware version that writes Delta to Lakehouse:
   ```python
   def save_dataframe(df, path_no_ext):
       table_name = Path(path_no_ext).name
       (
           spark.createDataFrame(df)
           .write.mode("overwrite").format("delta")
           .saveAsTable(f"lakehouse.dbo.{table_name}")
       )
   ```
3. Inject `MOODLE_TOKEN` from Azure Key Vault into the notebook environment
4. Schedule `production_etl.ipynb` for daily auto-refresh
5. Repoint the Power BI semantic model from CSV to the Lakehouse Delta tables
6. Schema unchanged → dashboard works as-is

The schema-resistant design means the dashboard never needs to know whether ETL ran on a MacBook in a Jupyter notebook or on Fabric against a 50,000-row institutional Moodle.

---

## Troubleshooting

**"Pre-flight FAILED (token_invalid)"**
The Moodle token is rejected. Refresh at `${MOODLE_BASE_URL}/admin/tool/webservice/userselect.php` and update `.env`.

**"Course catalog empty from API"**
Token works but `core_course_get_courses` returned nothing. Check the token's user has access to courses, or check `usercourses` in the site_info response.

**"Real participants extracted: 0"**
Token works, courses found, but `core_enrol_get_enrolled_users` returned no users. The endpoint may still be blocked even when others work. Run `probe_moodle.ipynb` to confirm.

**"Real assessment data sparse/empty — using deterministic fallback."**
Normal during development. Real grade items don't exist for the sandbox cohort yet. Hybrid uses fallback.

**Power BI refresh fails after running ETL**
Most likely a column-name mismatch. Verify `fact_student_risk.csv` columns match what Power Query expects. Check the run summary's `data_source_summary` to see what mode the ETL ran in.
