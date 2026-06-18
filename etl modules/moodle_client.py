"""
etl.moodle_client
-----------------

Moodle REST API client.

Wraps the Moodle Web Services REST endpoint, returning structured
results that downstream code can branch on without try/except. Also
includes a pre-flight token check so the rest of the pipeline knows
whether to even attempt real extraction.

Configuration is read from environment variables ( env.):

    MOODLE_BASE_URL=https://spi.nsw.edu.au/learn
    MOODLE_TOKEN=4daf5db24f615a924be6299b5e3ba4ec

Both are loaded by the entry-point notebooks (hybrid_etl, production_etl,
probe_moodle) before importing this module.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import requests


# ============================================================
# Configuration (read at import time from env)
# ============================================================
MOODLE_BASE_URL: str = os.getenv("MOODLE_BASE_URL", "").strip().rstrip("/")
MOODLE_TOKEN: str = os.getenv("MOODLE_TOKEN", "").strip()
MOODLE_ENDPOINT: str = (
    f"{MOODLE_BASE_URL}/webservice/rest/server.php" if MOODLE_BASE_URL else ""
)

DEFAULT_TIMEOUT_SEC: int = 60
DEFAULT_USER_AGENT: str = "Mozilla/5.0 (At-Risk Dashboard ETL)"


# ============================================================
# Failure-mode classification
# Used by hybrid_etl to populate the data_source lineage column
# with a meaningful failure reason.
# ============================================================

def classify_failure(error: str | None) -> str:
    """
    Map a safe_call_moodle_api error string to a known failure mode.

    Returns one of:
        'token_invalid' / 'endpoint_blocked' / 'network_error' / 'unknown'
    """
    if not error:
        return "unknown"
    err_lower = error.lower()
    if "invalidtoken" in err_lower or "invalid token" in err_lower:
        return "token_invalid"
    if "accessexception" in err_lower or "access" in err_lower and "denied" in err_lower:
        return "endpoint_blocked"
    if any(s in err_lower for s in ["timeout", "connection", "network", "dns", "name resolution"]):
        return "network_error"
    return "unknown"


# ============================================================
# Generic API caller
# ============================================================

def call_moodle_api(
    wsfunction: str,
    params: Optional[dict[str, Any]] = None,
    http_method: str = "GET",
) -> Any:
    """
    Generic Moodle REST API caller. Returns the raw JSON response.

    Raises:
        ValueError if MOODLE_BASE_URL or MOODLE_TOKEN are missing.
        requests.HTTPError on non-2xx response.
    """
    if not MOODLE_ENDPOINT or not MOODLE_TOKEN:
        raise ValueError(
            "MOODLE_BASE_URL and/or MOODLE_TOKEN are not configured. "
            "Set them in .env or the notebook environment before calling."
        )

    payload = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": wsfunction,
        "moodlewsrestformat": "json",
    }
    if params:
        payload.update(params)

    headers = {
        "User-Agent": DEFAULT_USER_AGENT,
        "Accept": "application/json,text/plain,*/*",
    }

    if http_method.upper() == "POST":
        response = requests.post(
            MOODLE_ENDPOINT, data=payload, headers=headers, timeout=DEFAULT_TIMEOUT_SEC
        )
    else:
        response = requests.get(
            MOODLE_ENDPOINT, params=payload, headers=headers, timeout=DEFAULT_TIMEOUT_SEC
        )

    response.raise_for_status()
    return response.json()


def safe_call_moodle_api(
    wsfunction: str,
    params: Optional[dict[str, Any]] = None,
    http_method: str = "GET",
) -> dict[str, Any]:
    """
    Safe wrapper that always returns a structured result dict.

    Returns:
        {
            "success": bool,
            "function": str,
            "data": <response or None>,
            "error": str | None,
        }

    Even Moodle exceptions (invalid token, blocked endpoint, etc.)
    return success=False rather than raising — so downstream code
    can branch on the result without try/except.
    """
    if not MOODLE_BASE_URL or not MOODLE_TOKEN:
        return {
            "success": False,
            "function": wsfunction,
            "data": None,
            "error": "MOODLE_BASE_URL or MOODLE_TOKEN not configured",
        }

    try:
        result = call_moodle_api(wsfunction, params=params, http_method=http_method)

        # Moodle returns 200 OK with an exception body for handled errors
        if isinstance(result, dict) and result.get("exception"):
            return {
                "success": False,
                "function": wsfunction,
                "data": result,
                "error": f"{result.get('errorcode', 'exception')}: {result.get('message', '')}",
            }

        return {
            "success": True,
            "function": wsfunction,
            "data": result,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "function": wsfunction,
            "data": None,
            "error": str(e),
        }


# ============================================================
# Pre-flight health check
# ----------------------------
# Always call this BEFORE running the rest of the pipeline so you
# know whether real extraction is even possible.
# ============================================================

def preflight_check() -> dict[str, Any]:
    """
    Hit core_webservice_get_site_info to validate token + connectivity.

    Returns a dict including:
        {
            "ok": bool,
            "site_info": {... full response if ok, else None},
            "error": str | None,
            "failure_mode": 'token_invalid' / 'endpoint_blocked' / 'network_error' / 'unknown' / None,
        }
    """
    result = safe_call_moodle_api("core_webservice_get_site_info")
    if result["success"]:
        site = result["data"] if isinstance(result["data"], dict) else {}
        print(f"[moodle] Pre-flight OK: connected to '{site.get('sitename', '?')}' "
              f"as user '{site.get('username', '?')}' (id={site.get('userid', '?')})")
        return {
            "ok": True,
            "site_info": result["data"],
            "error": None,
            "failure_mode": None,
        }

    failure_mode = classify_failure(result["error"])
    print(f"[moodle] Pre-flight FAILED ({failure_mode}): {result['error']}")
    return {
        "ok": False,
        "site_info": None,
        "error": result["error"],
        "failure_mode": failure_mode,
    }


# ============================================================
# Specific endpoint wrappers
# ----------------------------
# Each returns the safe_call_moodle_api result dict so callers can
# branch on success/failure without try/except.
# ============================================================

def extract_site_info() -> dict[str, Any]:
    return safe_call_moodle_api("core_webservice_get_site_info")


def extract_all_courses() -> dict[str, Any]:
    return safe_call_moodle_api("core_course_get_courses")


def extract_course_participants(courseid: int) -> dict[str, Any]:
    return safe_call_moodle_api(
        "core_enrol_get_enrolled_users",
        params={"courseid": int(courseid)},
    )


def extract_user_grade_items(userid: int, courseid: int) -> dict[str, Any]:
    return safe_call_moodle_api(
        "gradereport_user_get_grade_items",
        params={"courseid": int(courseid), "userid": int(userid)},
    )


def extract_assignments_for_course(courseid: int) -> dict[str, Any]:
    return safe_call_moodle_api(
        "mod_assign_get_assignments",
        params={"courseids[0]": int(courseid)},
    )


def extract_assignment_submissions(assignmentid: int) -> dict[str, Any]:
    return safe_call_moodle_api(
        "mod_assign_get_submissions",
        params={"assignmentids[0]": int(assignmentid)},
    )


def extract_logs(courseid: int, userid: int = 0, limitnum: int = 100) -> dict[str, Any]:
    return safe_call_moodle_api(
        "core_report_log_get_logs",
        params={
            "courseid": int(courseid),
            "userid": int(userid),
            "limitfrom": 0,
            "limitnum": int(limitnum),
        },
    )
