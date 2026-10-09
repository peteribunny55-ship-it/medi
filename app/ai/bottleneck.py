from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


DEMO_NOTE = "DEMO ESTIMATES on SYNTHETIC DATA — NOT clinical or operational guarantees."


ABSOLUTE_HIGH_THRESHOLDS: dict[str, float] = {
    "Order to Lab TAT": 120.0,      # minutes
    "Queue to Service Start": 60.0,  # minutes
    "Admission to Discharge": 7.0 * 24.0 * 60.0,  # 7 days in minutes
}


def _percentile(values: np.ndarray, p: float) -> float:
    """Return the p-th percentile of finite floats, or NaN if insufficient data."""
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    return float(np.percentile(arr, float(p)))


def _to_minutes_series(start: pd.Series, end: pd.Series) -> np.ndarray:
    s = pd.to_datetime(start, errors="coerce")
    e = pd.to_datetime(end, errors="coerce")
    delta = (e - s).dt.total_seconds() / 60.0
    arr = delta.to_numpy(dtype=float)
    return np.where(arr < 0, np.nan, arr)


def _load_lab_step(conn, start_date: str) -> pd.DataFrame:
    sql = """
        SELECT COALESCE(department_id, -1) AS department_id,
               ordered_at,
               resulted_at
        FROM   lab_requests
        WHERE  ordered_at >= ?
    """
    df = pd.read_sql(sql, conn, params=[start_date])
    if df.empty:
        return df
    df["dwell_minutes"] = _to_minutes_series(df["ordered_at"], df["resulted_at"])
    return df


def _load_queue_step(conn, start_date: str) -> pd.DataFrame:
    sql = """
        SELECT department_id,
               created_at,
               service_started_at
        FROM   queue_tokens
        WHERE  created_at >= ?
          AND  service_started_at IS NOT NULL
    """
    df = pd.read_sql(sql, conn, params=[start_date])
    if df.empty:
        return df
    df["dwell_minutes"] = _to_minutes_series(df["created_at"], df["service_started_at"])
    return df


def _load_admission_step(conn, start_date: str) -> pd.DataFrame:
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sql = f"""
        SELECT COALESCE(
                 (SELECT department_id FROM beds b WHERE b.id = a.bed_id),
                 (SELECT department_id FROM doctors d WHERE d.id = a.doctor_id),
                 -1
               ) AS department_id,
               admitted_at,
               discharged_at,
               status
        FROM   admissions a
        WHERE  admitted_at >= ?
    """
    df = pd.read_sql(sql, conn, params=[start_date])
    if df.empty:
        return df
    end_times = np.where(
        df["discharged_at"].isna() | df["status"].astype(str).str.lower().isin(["admitted", "active"]),
        now_str,
        df["discharged_at"].astype(str),
    )
    df["_end"] = end_times
    df["dwell_minutes"] = _to_minutes_series(df["admitted_at"], df["_end"])
    return df


def _alert_level(step: str, median: float, p75_ref: float, p90_ref: float) -> str:
    if not np.isfinite(median):
        return "Low"
    abs_threshold = ABSOLUTE_HIGH_THRESHOLDS.get(step)
    if abs_threshold is not None and median > float(abs_threshold):
        return "High"
    if np.isfinite(p90_ref) and median > p90_ref:
        return "High"
    if np.isfinite(p75_ref) and median > p75_ref:
        return "Medium"
    return "Low"


def compute_bottlenecks(conn, lookback_days: int = 30) -> list[dict]:
    """Compute dwell-time bottlenecks across 3 workflow steps and persist them.

    Steps analysed:
      * ``Order to Lab TAT`` — lab_requests from ordered_at → resulted_at.
      * ``Queue to Service Start`` — queue_tokens from created_at → service_started_at.
      * ``Admission to Discharge`` — admissions from admitted_at → discharged_at
        (uses ``now()`` for still-active admissions).

    For each step and department the function computes median dwell minutes and
    compares it against the 75th and 90th percentiles of the same step's dwell
    times over the trailing 90 days. Absolute thresholds are also applied
    (Lab > 120 min, Queue > 60 min, Admission > 7 days) which independently
    trigger a ``High`` alert.

    Results are inserted into the ``bottleneck_records`` table.

    Args:
        conn: DB-API connection object.
        lookback_days: Window size (days ending today) used to compute the
            current medians. A separate 90-day window is always used for the
            historical percentile references.

    Returns:
        List of dicts, each describing a freshly-computed (step, department)
        bottleneck. Each dict contains keys: workflow_step, department_id,
        median_dwell_minutes, alert_level, sample_count, observed_at, note.
    """
    try:
        lookback_start = (date.today() - timedelta(days=max(1, lookback_days))).strftime("%Y-%m-%d 00:00:00")
        ref_start = (date.today() - timedelta(days=90)).strftime("%Y-%m-%d 00:00:00")

        loaders = {
            "Order to Lab TAT": _load_lab_step,
            "Queue to Service Start": _load_queue_step,
            "Admission to Discharge": _load_admission_step,
        }

        results: list[dict] = []
        now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for step, loader in loaders.items():
            # Reference distribution over last 90 days for percentile thresholds.
            try:
                ref_df = loader(conn, ref_start)
            except Exception:
                ref_df = pd.DataFrame()
            if ref_df is not None and not ref_df.empty and "dwell_minutes" in ref_df.columns:
                ref_values = ref_df["dwell_minutes"].dropna().to_numpy(dtype=float)
                ref_values = ref_values[np.isfinite(ref_values) & (ref_values >= 0)]
                p75_ref = _percentile(ref_values, 75.0)
                p90_ref = _percentile(ref_values, 90.0)
            else:
                p75_ref = float("nan")
                p90_ref = float("nan")

            # Current (lookback) per-dept medians.
            try:
                cur_df = loader(conn, lookback_start)
            except Exception:
                cur_df = pd.DataFrame()
            if cur_df is None or cur_df.empty or "dwell_minutes" not in cur_df.columns:
                continue

            valid = cur_df.dropna(subset=["dwell_minutes"]).copy()
            if valid.empty:
                continue
            valid["dwell_minutes"] = valid["dwell_minutes"].astype(float)
            valid = valid.loc[(np.isfinite(valid["dwell_minutes"])) & (valid["dwell_minutes"] >= 0)]

            if valid.empty:
                continue

            per_dept = valid.groupby("department_id", dropna=False)["dwell_minutes"].agg(
                median_dwell="median", sample_count="count"
            ).reset_index()

            for _, row in per_dept.iterrows():
                dept = row["department_id"]
                dept_id = None if (dept is None or (isinstance(dept, (int, float)) and int(dept) < 0)) else int(dept)
                median = float(row["median_dwell"]) if np.isfinite(row["median_dwell"]) else float("nan")
                count = int(row["sample_count"])
                alert = _alert_level(step, median, p75_ref, p90_ref)
                rec = {
                    "workflow_step": step,
                    "department_id": dept_id,
                    "median_dwell_minutes": median if np.isfinite(median) else None,
                    "alert_level": alert,
                    "sample_count": count,
                    "observed_at": now_iso,
                    "note": DEMO_NOTE,
                }
                results.append(rec)

        # Persist rows.
        if results:
            insert_sql = """
                INSERT INTO bottleneck_records
                    (workflow_step, department_id, observed_at, median_dwell_minutes,
                     alert_level, sample_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """
            for rec in results:
                conn.execute(insert_sql, (
                    rec["workflow_step"],
                    rec["department_id"],
                    rec["observed_at"],
                    rec["median_dwell_minutes"],
                    rec["alert_level"],
                    int(rec["sample_count"]),
                ))
            try:
                conn.commit()
            except Exception:
                pass

        return results

    except Exception as exc:
        _ = exc
        return []


def get_recent_bottlenecks(conn, limit: int = 20) -> list[dict]:
    """Return most-recent bottleneck records from the bottleneck_records table.

    Args:
        conn: DB-API connection object.
        limit: Maximum number of records to return (default 20).

    Returns:
        List of dicts ordered by ``observed_at`` DESC. Each dict contains the
        persisted row columns plus a ``note`` flag noting the data is DEMO /
        synthetic.
    """
    try:
        sql = """
            SELECT id, workflow_step, department_id, observed_at,
                   median_dwell_minutes, alert_level, sample_count
            FROM   bottleneck_records
            ORDER  BY observed_at DESC
            LIMIT  ?
        """
        rows = pd.read_sql(sql, conn, params=[max(1, int(limit))])
        if rows.empty:
            return []
        out: list[dict] = []
        for rec in rows.to_dict(orient="records"):
            safe: dict[str, Any] = {}
            for k, v in rec.items():
                if isinstance(v, (np.floating,)):
                    safe[k] = float(v) if np.isfinite(v) else None
                elif isinstance(v, (np.integer,)):
                    safe[k] = int(v)
                elif isinstance(v, (pd.Timestamp, datetime)):
                    safe[k] = v.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    safe[k] = v
            safe["note"] = DEMO_NOTE
            out.append(safe)
        return out
    except Exception:
        return []


# Alias for backward compatibility across UI pages
detect_bottlenecks = compute_bottlenecks

