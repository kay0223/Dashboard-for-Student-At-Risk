"""
etl.mocks
---------

Mock data generators — used ONLY by hybrid_etl.

production_etl deliberately does not import this module so it can never
emit synthetic data, even by accident. This is enforced architecturally:
look for `from etl import mocks` in production_etl and you won't find it.

Two layers of mock generation are exposed:

  Layer 1 (cohort identity)  — generate_demo_cohort()
      Produces the 22 "Dummy" students with IDs 1001-1022

  Layer 2 (per-cell metrics) — simulate_metric_value()
      Deterministic synthetic metrics seeded by (student_id, course_id,
      base_seed). The same student-course pair always gets the same
      mocked values across runs, so partial real data doesn't shift
      mocked rows on each refresh.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np
import pandas as pd

from etl import schemas as S


# ============================================================
# The 22 demo students
# ============================================================

DEMO_STUDENT_NAMES: list[tuple[str, str]] = [
    ("Isabella", S.DEMO_STUDENT_LAST_NAME),
    ("Harper", S.DEMO_STUDENT_LAST_NAME),
    ("Logan", S.DEMO_STUDENT_LAST_NAME),
    ("Amelia", S.DEMO_STUDENT_LAST_NAME),
    ("Ethan", S.DEMO_STUDENT_LAST_NAME),
    ("Olivia", S.DEMO_STUDENT_LAST_NAME),
    ("Liam", S.DEMO_STUDENT_LAST_NAME),
    ("Sophia", S.DEMO_STUDENT_LAST_NAME),
    ("Noah", S.DEMO_STUDENT_LAST_NAME),
    ("Ava", S.DEMO_STUDENT_LAST_NAME),
    ("Mason", S.DEMO_STUDENT_LAST_NAME),
    ("Mia", S.DEMO_STUDENT_LAST_NAME),
    ("Lucas", S.DEMO_STUDENT_LAST_NAME),
    ("Charlotte", S.DEMO_STUDENT_LAST_NAME),
    ("Elijah", S.DEMO_STUDENT_LAST_NAME),
    ("Evelyn", S.DEMO_STUDENT_LAST_NAME),
    ("James", S.DEMO_STUDENT_LAST_NAME),
    ("Abigail", S.DEMO_STUDENT_LAST_NAME),
    ("Benjamin", S.DEMO_STUDENT_LAST_NAME),
    ("Emily", S.DEMO_STUDENT_LAST_NAME),
    ("Henry", S.DEMO_STUDENT_LAST_NAME),
    ("Grace", S.DEMO_STUDENT_LAST_NAME),
]


def generate_demo_cohort() -> pd.DataFrame:
    """
    Build the 22-student demo cohort dim_student dataframe.

    All students get role='student' (the demo cohort has no teachers).
    IDs run 1001..1022, matching the existing dashboard exactly.
    """
    df = pd.DataFrame(DEMO_STUDENT_NAMES, columns=["first_name", "last_name"])
    df["student_id"] = range(
        S.DEMO_STUDENT_ID_START,
        S.DEMO_STUDENT_ID_START + len(df),
    )
    df["full_name"] = df["first_name"] + " " + df["last_name"]
    df["username"] = (
        df["first_name"].str.lower() + "."
        + df["last_name"].str.lower()
        + df["student_id"].astype(str)
    )
    df["email"] = df["username"] + "@" + S.DEMO_EMAIL_DOMAIN
    df["role"] = "student"

    # Order columns to match the locked schema
    return df[S.DIM_STUDENT_COLUMNS].reset_index(drop=True)


def generate_demo_courses() -> pd.DataFrame:
    """Build the 2-course demo catalog matching the sandbox's real course IDs."""
    df = pd.DataFrame(S.DEMO_COURSES)
    return df[S.DIM_COURSE_COLUMNS].reset_index(drop=True)


# ============================================================
# Deterministic per-cell metric simulator
# ----------------------------
# Seed is derived from (student_id, course_id, base_seed) so the same
# pair always gets the same numbers — even when only some real data
# is available and the rest needs to be filled.
# ============================================================

def _deterministic_rng(
    base_seed: int, student_id: int, course_id: int, offset: int = 0
) -> np.random.Generator:
    """Build a numpy RNG seeded reproducibly by the (student, course) pair."""
    seed = int(base_seed + student_id * 13 + course_id * 17 + offset)
    return np.random.default_rng(seed)


def simulate_metric_value(
    student_id: int,
    course_id: int,
    base_seed: int = S.DEFAULT_BASE_SEED,
) -> dict[str, Any]:
    """
    Generate a deterministic mock metric tuple for one (student, course) row.

    Returns a dict ready to be merged into the cohort DataFrame:
        attendance_pct, avg_grade_pct, grade_item_count,
        days_since_last_login_simulated

    Distribution targets are chosen to roughly match the demo notebook
    output, so mock-mode hybrid runs reproduce the existing dashboard's
    risk distribution.
    """
    rng = _deterministic_rng(base_seed, int(student_id), int(course_id))

    attendance = round(float(np.clip(rng.normal(loc=82, scale=12), 45, 100)), 1)
    avg_grade = round(float(np.clip(rng.normal(loc=67, scale=15), 35, 98)), 1)
    grade_item_count = int(rng.integers(2, 6))
    days_since_login_sim = int(rng.integers(0, 21))

    return {
        "attendance_pct": attendance,
        "avg_grade_pct": avg_grade,
        "grade_item_count": grade_item_count,
        "days_since_last_login_simulated": days_since_login_sim,
    }


def enrich_with_per_cell_fallback(
    cohort_df: pd.DataFrame,
    base_seed: int = S.DEFAULT_BASE_SEED,
) -> pd.DataFrame:
    """
    Per-cell fallback: fill missing metric columns with deterministic mocks,
    keeping any real values that were already present.

    Input cohort_df may have these "real" columns (any may be missing/NaN):
        avg_grade_pct_real          — from gradereport_user_get_grade_items
        grade_item_count_real       — count of grade items returned
        lastaccess_unix             — from core_enrol_get_enrolled_users
        real_grade_available        — boolean per row

    Output cohort_df has the canonical fact columns:
        attendance_pct, avg_grade_pct, grade_item_count, days_since_last_login

    `attendance_pct` is ALWAYS simulated (no Moodle source available
    until mod_attendance is wired up). `days_since_last_login` is BLANK
    (NaN) when `lastaccess_unix == 0`, which the DAX layer interprets
    as the "Never Login" bin via ISBLANK().
    """
    df = cohort_df.copy()

    sim_rows = [
        simulate_metric_value(int(r["student_id"]), int(r["course_id"]), base_seed=base_seed)
        for _, r in df.iterrows()
    ]
    sim_df = pd.DataFrame(sim_rows)
    df = pd.concat([df.reset_index(drop=True), sim_df.reset_index(drop=True)], axis=1)

    # Attendance: always simulated until external attendance feed is wired.
    # (Already populated by simulate_metric_value above.)

    # Grades: real where available, simulated otherwise.
    if "real_grade_available" in df.columns and "avg_grade_pct_real" in df.columns:
        df["avg_grade_pct"] = np.where(
            df["real_grade_available"].fillna(False),
            df["avg_grade_pct_real"],
            df["avg_grade_pct"],   # already simulated
        )
        if "grade_item_count_real" in df.columns:
            df["grade_item_count"] = np.where(
                df["real_grade_available"].fillna(False),
                pd.to_numeric(df["grade_item_count_real"], errors="coerce").fillna(0).astype(int),
                df["grade_item_count"],
            )
    # else: simulated values stay as the only source

    # Days since last login:
    # - real value if lastaccess_unix > 0
    # - BLANK (NaN) if lastaccess_unix == 0 (drives "Never Login" bin)
    # - simulated value if lastaccess_unix is missing entirely (mock-mode fallback)
    if "lastaccess_unix" in df.columns:
        snapshot = pd.Timestamp.utcnow()
        def _resolve_login_days(row):
            la = row.get("lastaccess_unix")
            if pd.isna(la):
                # No real signal at all → use simulated (mock-mode path)
                return row["days_since_last_login_simulated"]
            if la in (0, "0", None, ""):
                # Real signal says "never logged in" → BLANK
                return np.nan
            try:
                ts = pd.to_datetime(int(la), unit="s", utc=True)
                return int(max(0, (snapshot - ts).days))
            except Exception:
                return row["days_since_last_login_simulated"]

        df["days_since_last_login"] = df.apply(_resolve_login_days, axis=1)
    else:
        df["days_since_last_login"] = df["days_since_last_login_simulated"]

    # Drop the working columns
    drop_cols = [c for c in [
        "days_since_last_login_simulated",
        "real_grade_available",
        "avg_grade_pct_real",
        "grade_item_count_real",
    ] if c in df.columns]
    if drop_cols:
        df = df.drop(columns=drop_cols)

    return df


# ============================================================
# Fallback assessment-table builder
# ----------------------------
# When real grade items can't be extracted, generate a stable
# 3-per-course-per-student assessment grid derived from the
# cohort's existing avg_grade_pct values.
# ============================================================

def build_fallback_assessment_tables(
    fact_student_risk: pd.DataFrame,
    dim_student: pd.DataFrame,
    dim_course: pd.DataFrame,
    base_seed: int = S.DEFAULT_BASE_SEED,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Generate fact_assessment and dim_assessment tables when no real
    Moodle assessment data is available.

    Grain:
        - dim_assessment: 3 rows per course (Assignment 1, Quiz 1, Exam 1)
        - fact_assessment: 3 rows per (student × course) pair

    The grade for each assessment is derived from the student's
    avg_grade_pct on that course, plus a small deterministic jitter so
    distribution charts have variance.

    Only STUDENTS appear in fact_assessment (teachers in dim_student
    are excluded — same filter as fact_student_risk).
    """
    rng = np.random.default_rng(base_seed)
    fact_rows: list[dict[str, Any]] = []
    dim_rows: list[dict[str, Any]] = []

    if fact_student_risk.empty or dim_course.empty:
        return pd.DataFrame(), pd.DataFrame()

    now_iso = pd.Timestamp.utcnow().isoformat()
    today_iso = pd.Timestamp.utcnow().date().isoformat()

    for _, course in dim_course.drop_duplicates("course_id").iterrows():
        course_id = int(course["course_id"])
        for idx, assessment_type in enumerate(S.ASSESSMENT_TYPES, start=1):
            # ID uses idx so each course's three assessments get unique IDs.
            # Name uses "1" since there's only one of each type per course.
            assessment_id = f"{course_id}_A{idx}"
            assessment_name = f"{assessment_type} 1"
            max_grade = S.DEFAULT_ASSESSMENT_MAX_GRADE

            dim_rows.append({
                "assessment_id": assessment_id,
                "course_id": course_id,
                "assessment_name": assessment_name,
                "assessment_type": assessment_type,
                "max_grade": max_grade,
                "due_date": None,
            })

            student_course_rows = fact_student_risk[fact_student_risk["course_id"] == course_id]
            for _, student in student_course_rows.iterrows():
                base_grade = pd.to_numeric(student.get("avg_grade_pct", np.nan), errors="coerce")
                if pd.isna(base_grade):
                    base_grade = 65.0
                grade_pct = float(np.clip(base_grade + rng.normal(0, 8), 0, 100))
                grade_pct = round(grade_pct, 2)

                days_since_login = pd.to_numeric(
                    student.get("days_since_last_login", 0), errors="coerce"
                )
                if pd.isna(days_since_login):
                    days_since_login = 0

                is_missing = int(days_since_login > 14 and grade_pct < 50)
                is_late = int(days_since_login > 14 and not is_missing)
                if is_missing:
                    submission_status = "Missing"
                elif is_late:
                    submission_status = "Late"
                else:
                    submission_status = "Submitted"

                fact_rows.append({
                    "student_id": int(student["student_id"]),
                    "course_id": course_id,
                    "assessment_id": assessment_id,
                    "assessment_name": assessment_name,
                    "assessment_type": assessment_type,
                    "grade": np.nan if is_missing else grade_pct,
                    "max_grade": max_grade,
                    "grade_pct": np.nan if is_missing else grade_pct,
                    "submission_status": submission_status,
                    "submitted_at": None,
                    "due_date": None,
                    "days_late": int(max(0, days_since_login - 7)) if is_late else 0,
                    "is_late": is_late,
                    "is_missing": is_missing,
                    "is_below_pass": int((not is_missing) and grade_pct < 50),
                    "data_source": S.DATA_SOURCE_ASSESSMENT_FALLBACK,
                    "etl_loaded_at": now_iso,
                    "etl_load_date": today_iso,
                })

    return pd.DataFrame(fact_rows), pd.DataFrame(dim_rows)
