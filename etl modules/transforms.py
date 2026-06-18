"""
etl.transforms
--------------

Pure transform functions — Moodle API JSON in, normalised pandas
DataFrames out. No I/O, no fallback logic, no random data.

These functions are shared by hybrid_etl and production_etl. The
difference between the two pipelines lives at a higher level (which
extracts they call, what they do when extracts return nothing).

All build_*() functions ENFORCE the column contract from etl.schemas
as their last step — column order, missing columns filled with NaN,
extra columns dropped. This guarantees the dashboard contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from etl import schemas as S


# ============================================================
# Small utilities
# ============================================================

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def unix_to_datetime(value: Any) -> pd.Timestamp:
    """Convert a Moodle Unix timestamp (seconds) to a pandas Timestamp.
    Returns NaT for None/empty/0 values."""
    if pd.isna(value) or value in (None, "", 0):
        return pd.NaT
    try:
        return pd.Timestamp(int(value), unit="s", tz="UTC")
    except Exception:
        return pd.NaT


def normalise_grade_value(value: Any) -> float:
    """Parse a Moodle grade value into a float (0..100 or raw)."""
    if value in (None, "", "-", "None"):
        return float("nan")
    try:
        return float(str(value).replace("%", "").strip())
    except Exception:
        return float("nan")


def classify_assessment_type(item_name: str | None = None,
                              item_type: str | None = None) -> str:
    """Heuristic classifier for assessment type from name/type strings."""
    text = f"{item_type or ''} {item_name or ''}".lower()
    if "quiz" in text:
        return "Quiz"
    if "exam" in text or "final" in text or "midterm" in text:
        return "Exam"
    if "assign" in text or "assessment" in text or "task" in text:
        return "Assignment"
    return "Assessment"


def classify_role(roles_array: list[dict] | None) -> str:
    """
    Pick a single role string from Moodle's roles array.

    A user can have multiple roles in a course; we pick the most
    specific teaching role if any, else 'student', else the first
    available role name.
    """
    if not roles_array or not isinstance(roles_array, list):
        return "unknown"

    role_names = []
    for role in roles_array:
        if isinstance(role, dict):
            roleid = role.get("roleid")
            mapped = S.MOODLE_ROLE_MAP.get(int(roleid)) if roleid is not None else None
            if mapped:
                role_names.append(mapped)
            elif role.get("shortname"):
                role_names.append(str(role["shortname"]))

    # Priority: editingteacher > teacher > student > others
    for preferred in ("editingteacher", "teacher", "student"):
        if preferred in role_names:
            return preferred
    return role_names[0] if role_names else "unknown"


# ============================================================
# Site / catalog transforms
# ============================================================

def transform_site_info(site_info_result: dict) -> pd.DataFrame:
    if not site_info_result.get("success") or not isinstance(site_info_result.get("data"), dict):
        return pd.DataFrame(columns=S.DIM_SITE_COLUMNS)

    site = site_info_result["data"]
    row = {
        "site_id": 1,
        "site_name": site.get("sitename"),
        "site_url": site.get("siteurl"),
        "current_user_id": site.get("userid"),
        "current_user_name": site.get("fullname"),
        "current_user_username": site.get("username"),
        "downloaded_at_utc": now_utc().isoformat(),
    }
    return pd.DataFrame([row])[S.DIM_SITE_COLUMNS]


def transform_course_catalog(
    all_courses_result: dict,
    fallback_site_info_result: dict,
) -> pd.DataFrame:
    """
    Build a course catalog from accessible API data.

    Priority:
      1. core_course_get_courses if available
      2. usercourses list embedded in site info
      3. empty DataFrame (caller should substitute demo fallback)
    """
    if (
        all_courses_result.get("success")
        and isinstance(all_courses_result.get("data"), list)
        and len(all_courses_result["data"]) > 0
    ):
        df = pd.DataFrame(all_courses_result["data"])
        return _normalize_course_columns(df)

    if (
        fallback_site_info_result.get("success")
        and isinstance(fallback_site_info_result.get("data"), dict)
    ):
        usercourses = fallback_site_info_result["data"].get("usercourses", [])
        if usercourses:
            return _normalize_course_columns(pd.DataFrame(usercourses))

    return pd.DataFrame(columns=S.DIM_COURSE_COLUMNS)


def _normalize_course_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Rename Moodle's course fields to our canonical names."""
    rename_map = {"id": "course_id", "shortname": "course_shortname", "fullname": "course_name"}
    for old, new in rename_map.items():
        if old in df.columns:
            df = df.rename(columns={old: new})
    for col in S.DIM_COURSE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[S.DIM_COURSE_COLUMNS].copy()


# ============================================================
# Participant transforms
# ============================================================

def transform_course_participants(
    participant_results: dict[int, dict],
) -> pd.DataFrame:
    """
    Flatten enrolled-users responses across courses into a single
    cohort-aligned dataframe.

    Output columns:
        student_id, course_id, full_name, first_name, last_name,
        email, username, role, lastaccess_unix, has_login

    The `role` column is derived from the Moodle roles array per
    enrolment. A user enrolled as student in one course and teacher
    in another will appear with both roles in different rows.
    """
    rows: list[dict[str, Any]] = []

    for course_id, result in participant_results.items():
        if not result.get("success") or not isinstance(result.get("data"), list):
            continue

        for user in result["data"]:
            uid = user.get("id")
            if uid in (None, "", 0):
                continue

            first = str(user.get("firstname") or "").strip()
            last = str(user.get("lastname") or "").strip()
            full = str(user.get("fullname") or f"{first} {last}".strip()).strip()
            email = user.get("email")
            username = user.get("username")
            lastaccess = user.get("lastaccess")
            role = classify_role(user.get("roles"))

            rows.append({
                "student_id": int(uid),
                "course_id": int(course_id),
                "first_name": first,
                "last_name": last,
                "full_name": full or username or str(uid),
                "email": email,
                "username": username,
                "role": role,
                "lastaccess_unix": lastaccess,
                "has_login": 1 if lastaccess not in (None, "", 0) else 0,
            })

    if not rows:
        return pd.DataFrame(columns=[
            "student_id", "course_id", "first_name", "last_name", "full_name",
            "email", "username", "role", "lastaccess_unix", "has_login",
        ])

    return (
        pd.DataFrame(rows)
        .drop_duplicates(subset=["student_id", "course_id"])
        .reset_index(drop=True)
    )


# ============================================================
# Grade item transforms
# ============================================================

def transform_grade_items_summary(
    grade_result: dict, userid: int, courseid: int
) -> dict[str, Any]:
    """
    Aggregate a gradereport_user_get_grade_items response into a
    one-row summary suitable for the cohort_risk fact table.

    Output keys:
        student_id, course_id, real_grade_available,
        avg_grade_pct_real, missing_grade_count_real, grade_item_count_real
    """
    if not grade_result.get("success"):
        return _empty_grade_summary(userid, courseid)

    data = grade_result.get("data")
    items: list[dict] = []

    if isinstance(data, dict):
        usergrades = data.get("usergrades")
        if isinstance(usergrades, list) and usergrades:
            grade_items = usergrades[0].get("gradeitems", [])
            if isinstance(grade_items, list):
                items = grade_items
        elif isinstance(data.get("gradeitems"), list):
            items = data["gradeitems"]
    elif isinstance(data, list):
        items = data

    rows: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        # Skip course/category aggregates
        item_type_raw = item.get("itemtype") or item.get("itemmodule") or ""
        if str(item_type_raw).lower() in {"course", "category"}:
            continue

        pct = float("nan")
        pf = item.get("percentageformatted")
        if pf not in (None, "", "-"):
            pct = normalise_grade_value(pf)
        else:
            graderaw = item.get("graderaw")
            grademax = item.get("grademax")
            if graderaw is not None and grademax not in (None, 0, "0"):
                try:
                    pct = (float(graderaw) / float(grademax)) * 100
                except Exception:
                    pct = float("nan")

        rows.append({"pct": pct})

    if not rows:
        return _empty_grade_summary(userid, courseid)

    grade_df = pd.DataFrame(rows)
    grade_item_count = int(len(grade_df))
    valid = grade_df["pct"].dropna()
    avg = round(float(valid.mean()), 1) if not valid.empty else float("nan")
    missing = int(grade_df["pct"].isna().sum())

    return {
        "student_id": int(userid),
        "course_id": int(courseid),
        "real_grade_available": not pd.isna(avg),
        "avg_grade_pct_real": avg,
        "missing_grade_count_real": missing,
        "grade_item_count_real": grade_item_count,
    }


def _empty_grade_summary(userid: int, courseid: int) -> dict[str, Any]:
    return {
        "student_id": int(userid),
        "course_id": int(courseid),
        "real_grade_available": False,
        "avg_grade_pct_real": float("nan"),
        "missing_grade_count_real": float("nan"),
        "grade_item_count_real": 0,
    }


def transform_grade_items_to_assessment_rows(
    grade_result: dict, student_id: int, course_id: int
) -> tuple[list[dict], list[dict]]:
    """
    Convert a gradereport_user_get_grade_items response into per-assessment
    fact rows AND dim rows for fact_assessment / dim_assessment.

    Returns (fact_rows, dim_rows).
    """
    fact_rows: list[dict] = []
    dim_rows: list[dict] = []

    if not grade_result.get("success") or not isinstance(grade_result.get("data"), dict):
        return fact_rows, dim_rows

    now_iso = now_utc().isoformat()
    today_iso = now_utc().date().isoformat()

    usergrades = grade_result["data"].get("usergrades", [])
    for usergrade in usergrades:
        for item in usergrade.get("gradeitems", []):
            item_name = item.get("itemname")
            if not item_name:
                continue

            item_type_raw = item.get("itemtype") or item.get("itemmodule") or ""
            if str(item_type_raw).lower() in {"course", "category"}:
                continue

            assessment_id = (
                item.get("id") or item.get("iteminstance") or f"{course_id}_{item_name}"
            )
            max_grade = normalise_grade_value(item.get("grademax"))
            grade = normalise_grade_value(item.get("graderaw"))

            if pd.notna(grade) and pd.notna(max_grade) and max_grade > 0:
                grade_pct = round((grade / max_grade) * 100, 2)
            else:
                pf_pct = normalise_grade_value(item.get("percentageformatted"))
                grade_pct = round(pf_pct, 2) if pd.notna(pf_pct) else float("nan")

            assessment_type = classify_assessment_type(
                item_name=item_name, item_type=item_type_raw
            )
            due_date = unix_to_datetime(item.get("duedate"))
            submitted_at = unix_to_datetime(item.get("datesubmitted"))

            submission_status = "Missing" if pd.isna(grade_pct) else "Submitted"
            days_late = float("nan")
            is_late = 0
            if pd.notna(due_date) and pd.notna(submitted_at):
                days_late = max(0, int((submitted_at - due_date).total_seconds() / 86400))
                is_late = int(days_late > 0)
                if is_late:
                    submission_status = "Late"

            fact_rows.append({
                "student_id": int(student_id),
                "course_id": int(course_id),
                "assessment_id": str(assessment_id),
                "assessment_name": item_name,
                "assessment_type": assessment_type,
                "grade": grade,
                "max_grade": max_grade,
                "grade_pct": grade_pct,
                "submission_status": submission_status,
                "submitted_at": submitted_at.isoformat() if pd.notna(submitted_at) else None,
                "due_date": due_date.isoformat() if pd.notna(due_date) else None,
                "days_late": days_late,
                "is_late": int(is_late),
                "is_missing": int(pd.isna(grade_pct)),
                "is_below_pass": int(pd.notna(grade_pct) and grade_pct < 50),
                "data_source": S.DATA_SOURCE_ASSESSMENT_REAL,
                "etl_loaded_at": now_iso,
                "etl_load_date": today_iso,
            })

            dim_rows.append({
                "assessment_id": str(assessment_id),
                "course_id": int(course_id),
                "assessment_name": item_name,
                "assessment_type": assessment_type,
                "max_grade": max_grade,
                "due_date": due_date.isoformat() if pd.notna(due_date) else None,
            })

    return fact_rows, dim_rows


def transform_assignments_to_dim_rows(
    assignments_result: dict, course_id: int
) -> list[dict]:
    """Flatten mod_assign_get_assignments response into dim_assessment rows."""
    rows: list[dict] = []
    if not assignments_result.get("success") or not isinstance(assignments_result.get("data"), dict):
        return rows

    for course in assignments_result["data"].get("courses", []):
        for assn in course.get("assignments", []):
            aid = assn.get("id")
            if aid is None:
                continue
            due_date = unix_to_datetime(assn.get("duedate"))
            rows.append({
                "assessment_id": str(aid),
                "course_id": int(course_id),
                "assessment_name": assn.get("name") or f"Assignment {aid}",
                "assessment_type": "Assignment",
                "max_grade": normalise_grade_value(assn.get("grade")),
                "due_date": due_date.isoformat() if pd.notna(due_date) else None,
            })
    return rows


# ============================================================
# Star-schema builders (enforce locked column contract)
# ============================================================

def build_dim_student(participants_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build the canonical dim_student table from a participants dataframe.

    Input must have at least: student_id, full_name. Other identity
    columns (first_name, last_name, email, username, role) are kept
    if present, derived if not.

    Output columns are exactly DIM_STUDENT_COLUMNS, deduplicated by
    student_id (keeping the row with a non-empty role if available).
    """
    df = participants_df.copy()

    # Derive missing name fields from full_name where possible
    if "full_name" not in df.columns and "student_name" in df.columns:
        df["full_name"] = df["student_name"]
    if "first_name" not in df.columns and "full_name" in df.columns:
        df["first_name"] = df["full_name"].astype(str).str.strip().str.split().str[0]
    if "last_name" not in df.columns and "full_name" in df.columns:
        split_names = df["full_name"].astype(str).str.strip().str.split()
        df["last_name"] = split_names.apply(lambda x: " ".join(x[1:]) if len(x) > 1 else "")

    for col in S.DIM_STUDENT_COLUMNS:
        if col not in df.columns:
            df[col] = None

    # Deduplicate by student_id, preferring rows where role is non-empty
    df["_role_priority"] = df["role"].fillna("").apply(lambda r: 0 if r else 1)
    df = (
        df.sort_values(["student_id", "_role_priority"])
        .drop_duplicates(subset=["student_id"], keep="first")
        .drop(columns=["_role_priority"])
    )

    return df[S.DIM_STUDENT_COLUMNS].reset_index(drop=True)


def build_dim_course(course_df: pd.DataFrame) -> pd.DataFrame:
    """Enforce the dim_course schema."""
    df = course_df.copy()
    for col in S.DIM_COURSE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[S.DIM_COURSE_COLUMNS].drop_duplicates().reset_index(drop=True)


def build_dim_site(
    site_df: pd.DataFrame, base_url_fallback: str | None = None
) -> pd.DataFrame:
    """Enforce dim_site schema, with a fallback row if site_df is empty."""
    if site_df is None or site_df.empty:
        return pd.DataFrame([{
            "site_id": 1,
            "site_name": "Sandbox Moodle",
            "site_url": base_url_fallback,
            "current_user_id": None,
            "current_user_name": None,
            "current_user_username": None,
            "downloaded_at_utc": now_utc().isoformat(),
        }])[S.DIM_SITE_COLUMNS]
    df = site_df.copy()
    for col in S.DIM_SITE_COLUMNS:
        if col not in df.columns:
            df[col] = None
    return df[S.DIM_SITE_COLUMNS]


def build_dim_date(fact_df: pd.DataFrame) -> pd.DataFrame:
    """Build a small dim_date from the etl_load_date in a fact table."""
    if fact_df.empty or "etl_load_date" not in fact_df.columns:
        return pd.DataFrame(columns=S.DIM_DATE_COLUMNS)

    dates = (
        pd.to_datetime(fact_df["etl_load_date"], errors="coerce")
        .dropna()
        .drop_duplicates()
        .sort_values()
    )

    df = pd.DataFrame({"date": dates.dt.date.astype(str)})
    df["year"] = pd.to_datetime(df["date"]).dt.year
    df["month"] = pd.to_datetime(df["date"]).dt.month
    df["month_name"] = pd.to_datetime(df["date"]).dt.month_name()
    df["day"] = pd.to_datetime(df["date"]).dt.day
    df["quarter"] = pd.to_datetime(df["date"]).dt.quarter
    return df[S.DIM_DATE_COLUMNS].reset_index(drop=True)


def build_fact_student_risk(
    cohort_risk_df: pd.DataFrame,
    data_source: str,
    students_only: bool = True,
    student_role_filter: pd.Series | None = None,
) -> pd.DataFrame:
    """
    Build the canonical fact_student_risk table.

    Args:
        cohort_risk_df: cohort dataframe AFTER risk scoring (must have all
            risk columns including risk_score, risk_level, risk_high_*, etc).
        data_source: lineage value to populate the data_source column.
            One of S.DATA_SOURCE_*.
        students_only: if True, exclude any rows where role indicates teacher.
        student_role_filter: optional explicit boolean mask of rows to keep.

    Returns a dataframe with exactly FACT_STUDENT_RISK_COLUMNS in order.
    """
    df = cohort_risk_df.copy()

    # Exclude teachers from the at-risk fact table.
    if students_only and "role" in df.columns:
        df = df[df["role"].fillna("student").isin(S.STUDENT_ROLES)].copy()
    if student_role_filter is not None:
        df = df[student_role_filter].copy()

    # Populate ETL audit columns
    if "etl_loaded_at" not in df.columns:
        df["etl_loaded_at"] = now_utc().isoformat()
    if "etl_load_date" not in df.columns:
        df["etl_load_date"] = pd.to_datetime(df["etl_loaded_at"]).dt.date.astype(str)

    # Populate lineage column
    if "data_source" not in df.columns:
        df["data_source"] = data_source
    else:
        # Allow per-row overrides if upstream already set it
        df["data_source"] = df["data_source"].fillna(data_source)

    # grade_item_count fallback
    if "grade_item_count" not in df.columns:
        df["grade_item_count"] = S.DEFAULT_GRADE_ITEM_COUNT

    # Boolean flag types: keep as bool (matches demo)
    for flag in (
        "risk_high_attendance", "risk_moderate_attendance",
        "risk_high_grade", "risk_moderate_grade",
        "risk_high_last_login", "risk_moderate_last_login",
    ):
        if flag in df.columns:
            df[flag] = df[flag].fillna(False).astype(bool)
        else:
            df[flag] = False

    # Fill any missing canonical column
    for col in S.FACT_STUDENT_RISK_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan

    return df[S.FACT_STUDENT_RISK_COLUMNS].reset_index(drop=True)


def build_fact_assessment(rows_df: pd.DataFrame) -> pd.DataFrame:
    """Enforce the fact_assessment schema."""
    df = rows_df.copy()
    if df.empty:
        return pd.DataFrame(columns=S.FACT_ASSESSMENT_COLUMNS)
    for col in S.FACT_ASSESSMENT_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    return df[S.FACT_ASSESSMENT_COLUMNS].reset_index(drop=True)


def build_dim_assessment(rows_df: pd.DataFrame) -> pd.DataFrame:
    """Enforce the dim_assessment schema with deduplication."""
    df = rows_df.copy()
    if df.empty:
        return pd.DataFrame(columns=S.DIM_ASSESSMENT_COLUMNS)
    for col in S.DIM_ASSESSMENT_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    return (
        df[S.DIM_ASSESSMENT_COLUMNS]
        .drop_duplicates(subset=["assessment_id", "course_id"])
        .reset_index(drop=True)
    )
