"""
At-Risk Student Dashboard — ETL package

This package implements a schema-resistant ETL pipeline that feeds the
Power BI dashboard for at-risk student identification. Two entry points
sit on top of this package:

  * hybrid_etl.ipynb     — development phase (real Moodle + per-cell mock fallback)
  * production_etl.ipynb — production phase (real Moodle only, fail-loud)

Both produce IDENTICAL output schemas, so the dashboard is completely
agnostic to which one ran.
"""

__version__ = "1.0.0"
