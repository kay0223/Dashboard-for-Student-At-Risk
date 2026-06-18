"""
etl.io
------

I/O abstraction layer for the ETL pipeline.

Today this writes CSV + Parquet to a local folder so the user can
re-upload to Power BI Web. When migrating to Microsoft Fabric, only
this file changes — the rest of the ETL is untouched. The Fabric
version writes to a Lakehouse Delta table:

    # Future Fabric io.py — drop-in replacement
    def save_dataframe(df, path_no_ext):
        table_name = Path(path_no_ext).name
        spark.createDataFrame(df).write.mode("overwrite") \\
             .format("delta").saveAsTable(f"lakehouse.dbo.{table_name}")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd


def ensure_dirs(*paths: Path) -> None:
    """Create directories if they don't exist."""
    for p in paths:
        Path(p).mkdir(parents=True, exist_ok=True)


def save_dataframe(df: pd.DataFrame | None, path_no_ext: Path | str) -> None:
    """
    Save a DataFrame to CSV (always) and Parquet (best effort).

    Uses atomic write-then-rename so a failed save doesn't leave a
    partial file that Power BI might pick up on the next refresh.

    Args:
        df: DataFrame to save. If None or empty, the save is skipped
            (with a console message). This is intentional — better to
            skip than emit an empty file that Power BI would interpret
            as "all rows deleted".
        path_no_ext: Output base path (with or without .csv/.parquet
            suffix). The function strips the suffix and writes both
            formats next to each other.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        print(f"[io] Skipped empty output: {Path(path_no_ext).name}")
        return

    path_no_ext = Path(path_no_ext)
    path_no_ext.parent.mkdir(parents=True, exist_ok=True)

    if path_no_ext.suffix.lower() in {".csv", ".parquet"}:
        base_path = path_no_ext.with_suffix("")
    else:
        base_path = path_no_ext

    csv_path = base_path.with_suffix(".csv")
    parquet_path = base_path.with_suffix(".parquet")

    # CSV — atomic
    temp_csv = csv_path.with_suffix(".csv.tmp")
    df.to_csv(temp_csv, index=False)
    temp_csv.replace(csv_path)
    print(f"[io] Saved CSV: {csv_path.name}  ({len(df)} rows)")

    # Parquet — best effort, atomic
    try:
        temp_parquet = parquet_path.with_suffix(".parquet.tmp")
        df.to_parquet(temp_parquet, index=False)
        temp_parquet.replace(parquet_path)
        print(f"[io] Saved Parquet: {parquet_path.name}")
    except Exception as e:
        print(f"[io] Parquet skipped for {parquet_path.name}: {e}")


def save_json(data: Any, output_path: Path | str) -> None:
    """Save arbitrary JSON-serialisable data, with parent dir creation."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)


def safe_read_csv(path: Path | str) -> pd.DataFrame:
    """Read a CSV if it exists, otherwise return an empty DataFrame."""
    path = Path(path)
    if path.exists():
        return pd.read_csv(path)
    print(f"[io] File not found: {path}")
    return pd.DataFrame()
