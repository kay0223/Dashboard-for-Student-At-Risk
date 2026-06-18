"""
etl.risk
--------

Risk scoring logic.

Thresholds and weights live in etl.schemas — change them there only.

Risk score grain: one row per (student_id, course_id) pair in
fact_student_risk. The Power BI dashboard uses MAX(risk_score) per
student to determine "worst course wins" classification.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from etl import schemas as S


# ============================================================
# Per-row scoring
# ============================================================

def calculate_risk_score(
    attendance_pct: Optional[float],
    avg_grade_pct: Optional[float],
    days_since_last_login: Optional[float],
) -> int:
    """
    Compute the additive risk score for a single (student, course) row.

    Score range: 0 .. 9 (three indicators × WEIGHT_HIGH=3 max each).

    NaN inputs are treated as "no signal" and contribute 0. This is
    important for `days_since_last_login` which is BLANK for never-logged-in
    students — those rows should not score risk on the login indicator
    (the dashboard's "Never Login" bin handles those cases via DAX).
    """
    score = 0

    # Attendance
    if not _is_missing(attendance_pct):
        if attendance_pct < S.ATTENDANCE_HIGH_RISK_BELOW:
            score += S.WEIGHT_HIGH_FLAG
        elif attendance_pct < S.ATTENDANCE_MODERATE_RISK_BELOW:
            score += S.WEIGHT_MODERATE_FLAG

    # Grade
    if not _is_missing(avg_grade_pct):
        if avg_grade_pct < S.GRADE_HIGH_RISK_BELOW:
            score += S.WEIGHT_HIGH_FLAG
        elif avg_grade_pct < S.GRADE_MODERATE_RISK_BELOW:
            score += S.WEIGHT_MODERATE_FLAG

    # Login recency
    if not _is_missing(days_since_last_login):
        if days_since_last_login > S.LOGIN_HIGH_RISK_DAYS_ABOVE:
            score += S.WEIGHT_HIGH_FLAG
        elif days_since_last_login > S.LOGIN_MODERATE_RISK_DAYS_ABOVE:
            score += S.WEIGHT_MODERATE_FLAG

    return int(score)


def derive_risk_level(risk_score: Optional[int]) -> str:
    """Map a risk_score (0..9) to 'High' / 'Medium' / 'Low' / 'Unknown'."""
    if risk_score is None or pd.isna(risk_score):
        return "Unknown"
    if risk_score >= S.RISK_HIGH_SCORE:
        return "High"
    if risk_score >= S.RISK_MEDIUM_SCORE:
        return "Medium"
    return "Low"


def derive_recommended_action(risk_level: str) -> str:
    """Map a risk_level string to the recommended action text."""
    return {
        "High": S.ACTION_HIGH,
        "Medium": S.ACTION_MEDIUM,
        "Low": S.ACTION_LOW,
    }.get(risk_level, S.ACTION_UNKNOWN)


# ============================================================
# Vectorised application across the full cohort fact table
# ============================================================

def apply_final_risk_logic(cohort_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute risk_score, risk_level, recommended_action, and the six
    backward-compatible boolean risk flags on a (student × course) DataFrame.

    Required input columns:
        attendance_pct, avg_grade_pct, days_since_last_login

    Returns a copy of `cohort_df` with the risk columns appended.
    """
    df = cohort_df.copy()

    df["risk_score"] = df.apply(
        lambda r: calculate_risk_score(
            r.get("attendance_pct"),
            r.get("avg_grade_pct"),
            r.get("days_since_last_login"),
        ),
        axis=1,
    )

    df["risk_level"] = df["risk_score"].apply(derive_risk_level)
    df["recommended_action"] = df["risk_level"].apply(derive_recommended_action)

    # Backward-compatible boolean flags. The current dashboard's DAX
    # measures don't read these directly (they recompute from the raw
    # columns), but they're emitted for any downstream consumer that
    # relied on the demo schema.
    df["risk_high_attendance"] = (
        df["attendance_pct"].lt(S.ATTENDANCE_HIGH_RISK_BELOW).fillna(False)
    )
    df["risk_moderate_attendance"] = (
        df["attendance_pct"].ge(S.ATTENDANCE_HIGH_RISK_BELOW)
        & df["attendance_pct"].lt(S.ATTENDANCE_MODERATE_RISK_BELOW)
    ).fillna(False)

    df["risk_high_grade"] = (
        df["avg_grade_pct"].lt(S.GRADE_HIGH_RISK_BELOW).fillna(False)
    )
    df["risk_moderate_grade"] = (
        df["avg_grade_pct"].ge(S.GRADE_HIGH_RISK_BELOW)
        & df["avg_grade_pct"].lt(S.GRADE_MODERATE_RISK_BELOW)
    ).fillna(False)

    df["risk_high_last_login"] = (
        df["days_since_last_login"].gt(S.LOGIN_HIGH_RISK_DAYS_ABOVE).fillna(False)
    )
    df["risk_moderate_last_login"] = (
        df["days_since_last_login"].gt(S.LOGIN_MODERATE_RISK_DAYS_ABOVE)
        & df["days_since_last_login"].le(S.LOGIN_HIGH_RISK_DAYS_ABOVE)
    ).fillna(False)

    return df


# ============================================================
# Helpers
# ============================================================

def _is_missing(value) -> bool:
    """True if value is None or NaN."""
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False
