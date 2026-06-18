"""
etl.schemas
-----------

The single source of truth for the dashboard data contract.

Every column name, type, threshold, and sentinel value used by the
Power BI model lives here. Both hybrid_etl and production_etl import
from this module, so changing a column name in one place is enough.

Why this matters:
    The dashboard's Power BI model has calculated columns and DAX
    measures that reference these column names by string. Any
    rename, removal, or type change here will break Power BI refresh
    until the DAX is updated. KEEP THIS FILE STABLE.
"""

from __future__ import annotations
from typing import Final


# ============================================================
# Risk thresholds and weights
# ----------------------------
# These values are matched by the Power BI DAX measures, e.g.
#   At Risk Students = MAX(risk_score) >= 7
# Changing them here requires updating the DAX bin definitions.
# ============================================================

# Per-indicator thresholds
ATTENDANCE_HIGH_RISK_BELOW: Final[float] = 70.0
ATTENDANCE_MODERATE_RISK_BELOW: Final[float] = 80.0

GRADE_HIGH_RISK_BELOW: Final[float] = 50.0
GRADE_MODERATE_RISK_BELOW: Final[float] = 65.0

LOGIN_HIGH_RISK_DAYS_ABOVE: Final[int] = 14
LOGIN_MODERATE_RISK_DAYS_ABOVE: Final[int] = 7

# Weights per flag (additive, contribute to risk_score 0..9)
WEIGHT_HIGH_FLAG: Final[int] = 3
WEIGHT_MODERATE_FLAG: Final[int] = 2

# Risk level cutoffs over risk_score (matches DAX: At Risk = score >= 7)
RISK_HIGH_SCORE: Final[int] = 7
RISK_MEDIUM_SCORE: Final[int] = 3


# ============================================================
# Recommended action text
# ============================================================
ACTION_HIGH: Final[str] = "Immediate outreach and advisor follow-up"
ACTION_MEDIUM: Final[str] = "Monitor closely and send early warning"
ACTION_LOW: Final[str] = "No immediate intervention required"
ACTION_UNKNOWN: Final[str] = "Review manually"


# ============================================================
# Moodle role IDs
# Default Moodle role assignments. roleid=5 is the standard student.
# ============================================================
MOODLE_ROLE_MAP: Final[dict[int, str]] = {
    1: "manager",
    2: "coursecreator",
    3: "editingteacher",
    4: "teacher",
    5: "student",
    6: "guest",
    7: "user",
    8: "frontpage",
}

STUDENT_ROLES: Final[set[str]] = {"student"}
TEACHER_ROLES: Final[set[str]] = {"teacher", "editingteacher"}


# ============================================================
# Cohort defaults (demo fallback)
# ============================================================
DEMO_COHORT_SIZE: Final[int] = 22
DEMO_STUDENT_ID_START: Final[int] = 1001
DEMO_STUDENT_LAST_NAME: Final[str] = "Dummy"
DEMO_EMAIL_DOMAIN: Final[str] = "sandbox.spi.nsw.edu.au"

DEFAULT_COHORT_THRESHOLD: Final[int] = 10
DEFAULT_BASE_SEED: Final[int] = 42

DEMO_COURSES: Final[list[dict]] = [
    {"course_id": 210, "course_shortname": "SC-1", "course_name": "Sample Course 1"},
    {"course_id": 211, "course_shortname": "SC-2", "course_name": "Sample Course 2"},
]


# ============================================================
# Data lineage values for the `data_source` column
# ----------------------------
# Tracked per row of fact_student_risk and fact_assessment so the
# dashboard can show coverage at any time, and so failure modes are
# diagnosable from the data itself.
# ============================================================
DATA_SOURCE_MOODLE_FULL: Final[str] = "moodle_full"
DATA_SOURCE_MOODLE_PARTIAL: Final[str] = "moodle_partial"
DATA_SOURCE_MOODLE_STUDENT_ONLY: Final[str] = "moodle_student_only"
DATA_SOURCE_MOCK_FULL: Final[str] = "mock_full"
DATA_SOURCE_MOCK_TOKEN_INVALID: Final[str] = "mock_full_token_invalid"
DATA_SOURCE_MOCK_ENDPOINT_BLOCKED: Final[str] = "mock_full_endpoint_blocked"
DATA_SOURCE_MOCK_NETWORK_ERROR: Final[str] = "mock_full_network_error"
DATA_SOURCE_MOCK_COHORT_TOO_SMALL: Final[str] = "mock_full_cohort_too_small"

DATA_SOURCE_ASSESSMENT_REAL: Final[str] = "moodle_grade_items"
DATA_SOURCE_ASSESSMENT_FALLBACK: Final[str] = "fallback_from_cohort"


# ============================================================
# Output schemas — the locked column contracts
# ----------------------------
# These lists define exactly which columns each output table contains
# and in what order. Used by build_* functions to enforce the schema
# at the very end of the pipeline.
# ============================================================

DIM_STUDENT_COLUMNS: Final[list[str]] = [
    "student_id",
    "username",
    "first_name",
    "last_name",
    "full_name",   # primary name field referenced by Power BI visuals
    "email",
    "role",        # 'student' / 'teacher' / 'editingteacher' 
]

DIM_COURSE_COLUMNS: Final[list[str]] = [
    "course_id",
    "course_shortname",
    "course_name",
]

DIM_SITE_COLUMNS: Final[list[str]] = [
    "site_id",
    "site_name",
    "site_url",
    "current_user_id",
    "current_user_name",
    "current_user_username",
    "downloaded_at_utc",
]

DIM_DATE_COLUMNS: Final[list[str]] = [
    "date", "year", "month", "month_name", "day", "quarter",
]

FACT_STUDENT_RISK_COLUMNS: Final[list[str]] = [
    "student_id",
    "course_id",
    "attendance_pct",
    "avg_grade_pct",
    "grade_item_count",
    "days_since_last_login",        # nullable (BLANK = "Never Login" bin in DAX)
    "risk_high_attendance",
    "risk_moderate_attendance",
    "risk_high_grade",
    "risk_moderate_grade",
    "risk_high_last_login",
    "risk_moderate_last_login",
    "risk_score",
    "risk_level",                   # "High" / "Medium" / "Low"
    "recommended_action",
    "data_source",                  # lineage column
    "etl_loaded_at",
    "etl_load_date",
]

DIM_ASSESSMENT_COLUMNS: Final[list[str]] = [
    "assessment_id",
    "course_id",
    "assessment_name",
    "assessment_type",      # 'Assignment' / 'Quiz' / 'Exam' / 'Assessment'
    "max_grade",
    "due_date",
]

FACT_ASSESSMENT_COLUMNS: Final[list[str]] = [
    "student_id",
    "course_id",
    "assessment_id",
    "assessment_name",
    "assessment_type",
    "grade",
    "max_grade",
    "grade_pct",
    "submission_status",    # 'Submitted' / 'Late' / 'Missing'
    "submitted_at",
    "due_date",
    "days_late",
    "is_late",
    "is_missing",
    "is_below_pass",
    "data_source",
    "etl_loaded_at",
    "etl_load_date",
]

ETL_RUN_SUMMARY_COLUMNS: Final[list[str]] = [
    "run_timestamp_utc",
    "pipeline",                     # 'hybrid' / 'production'
    "site_info_success",
    "course_catalog_success",
    "participant_extraction_mode",
    "real_participant_count",
    "student_count",
    "teacher_count",
    "course_count",
    "fact_rows",
    "real_grade_rows",
    "risk_low_count",
    "risk_medium_count",
    "risk_high_count",
    "assessment_fact_rows",
    "assessment_count",
    "assessment_data_source",
    "data_source_summary",
    "schema_note",
]


# ============================================================
# Default fallback values when something must be filled
# ============================================================

# When a fact column has no real source AND no mock source,
# this is the safe default. Should rarely be hit; if it does, the
# data_source column will record why.
DEFAULT_GRADE_ITEM_COUNT: Final[int] = 0

# When fallback assessment generation runs, this is the per-course count.
ASSESSMENTS_PER_COURSE: Final[int] = 3
ASSESSMENT_TYPES: Final[list[str]] = ["Assignment", "Quiz", "Exam"]
DEFAULT_ASSESSMENT_MAX_GRADE: Final[int] = 100
