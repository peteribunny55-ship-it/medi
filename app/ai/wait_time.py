from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

try:
    from sklearn.linear_model import LinearRegression as _LinearRegression
    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False
    _LinearRegression = None


DEMO_NOTE = "DEMO ESTIMATES on SYNTHETIC DATA — NOT clinical or operational guarantees."


def _safe_int_minutes(x: float) -> int:
    try:
        if x is None:
            return 0
        v = float(x)
        if not np.isfinite(v):
            return 0
        if v < 0:
            return 0
        return int(round(v))
    except Exception:
        return 0


def documented_estimate(patients_ahead: int, avg_service_minutes: float,
                        queue_length: int | None = None,
                        dow: int | None = None,
                        hour: int | None = None,
                        historical_coef: tuple[float, float, float, float] | None = None) -> tuple[int, str]:
    """Produce an integer wait-time estimate with a transparent end-user explanation.

    Args:
        patients_ahead: Count of patients that must be served before this one.
        avg_service_minutes: Historical average per-patient service minutes.
        queue_length: Optional total queue length (informational, included in the
            explanation when provided).
        dow: Optional day of week (0=Monday … 6=Sunday). Used as a feature to a
            trained linear adjustment when ``historical_coef`` is supplied.
        hour: Optional hour of day (0-23). Used as a feature to a trained linear
            adjustment when ``historical_coef`` is supplied.
        historical_coef: Optional 4-tuple (intercept, coef_baseline, coef_dow,
            coef_hour) produced by a LinearRegression trained on completed queue
            token waits. If None OR fewer than 50 completed tokens are available,
            no adjustment is applied.

    Returns:
        A 2-tuple ``(minutes_estimate, explanation_string)``. The explanation
        always includes the literal substring ``"Estimate = patients_ahead × avg_service_minutes"``
        and labels the value as an ``Estimate``.
    """
    try:
        patients_ahead_i = max(0, int(patients_ahead or 0))
        avg_svc = float(avg_service_minutes) if avg_service_minutes is not None else 15.0
        if not np.isfinite(avg_svc) or avg_svc < 0:
            avg_svc = 15.0

        baseline = float(patients_ahead_i) * avg_svc
        formula_line = f"Estimate = patients_ahead × avg_service_minutes = {patients_ahead_i} × {avg_svc:.2f} = {baseline:.2f} min"

        adjusted = baseline
        applied_adjustment = False
        adj_explain_parts: list[str] = []

        if historical_coef is not None and len(historical_coef) == 4:
            try:
                intercept, c_base, c_dow, c_hour = [float(v) for v in historical_coef]
                dow_v = float(dow) if dow is not None and 0 <= int(dow) <= 6 else 3.0
                hour_v = float(hour) if hour is not None and 0 <= int(hour) <= 23 else 11.0
                if not (np.isfinite(intercept) and np.isfinite(c_base) and np.isfinite(c_dow) and np.isfinite(c_hour)):
                    raise ValueError("non-finite coefficients")
                adjusted = intercept + c_base * baseline + c_dow * dow_v + c_hour * hour_v
                adjusted = max(0.0, adjusted)
                applied_adjustment = True
                adj_explain_parts.append(
                    f"Linear adjustment (dow={int(dow_v)}, hour={int(hour_v)}) applied."
                )
            except Exception:
                applied_adjustment = False
                adjusted = baseline

        final = _safe_int_minutes(adjusted)

        parts: list[str] = []
        parts.append("Wait Estimate (DEMO / synthetic data only — NOT guaranteed)")
        parts.append("")
        parts.append(f"Baseline formula: {formula_line}")
        parts.append(
            f"Inputs: patients_ahead={patients_ahead_i}, avg_service_minutes={avg_svc:.2f}"
            + (f", queue_length={int(queue_length)}" if queue_length is not None else "")
            + (f", dow={int(dow)}" if dow is not None else "")
            + (f", hour={int(hour)}" if hour is not None else "")
        )
        if applied_adjustment:
            parts.extend(adj_explain_parts)
            parts.append(
                f"Trained LinearRegression model refined the baseline → {adjusted:.2f} min."
            )
        else:
            parts.append(
                "Using baseline only — no historical linear adjustment applied "
                "(insufficient training data or no coefficients supplied)."
            )
        parts.append("")
        parts.append(f"Final Estimate: {final} minute(s). This is an Estimate; actual wait may differ significantly.")
        parts.append(f"Note: {DEMO_NOTE}")

        return final, "\n".join(parts)

    except Exception as exc:
        fallback = _safe_int_minutes(max(0, int(patients_ahead or 0)) * float(avg_service_minutes or 15.0))
        return fallback, (
            f"Wait Estimate (DEMO / synthetic data only — NOT guaranteed)\n\n"
            f"Estimate = patients_ahead × avg_service_minutes = {patients_ahead} × {avg_service_minutes} = {fallback} min\n"
            f"Note: Error during calculation ({type(exc).__name__}); returning baseline estimate. {DEMO_NOTE}"
        )


def historical_avg_service(conn, dept_id: int | None = None, days: int = 30) -> float:
    """Average service duration in minutes for completed queue tokens.

    Args:
        conn: DB-API connection.
        dept_id: Optional department filter for the queue tokens.
        days: Lookback window in days ending today.

    Returns:
        Mean of ``(completed_at - service_started_at)`` in minutes. Falls back
        to ``15.0`` if no rows are found or an error occurs.
    """
    try:
        start = (date.today() - timedelta(days=max(1, days))).strftime("%Y-%m-%d 00:00:00")
        clauses = ["status = 'Completed'", "service_started_at IS NOT NULL",
                   "completed_at IS NOT NULL", "completed_at >= ?"]
        params: list[Any] = [start]
        if dept_id is not None:
            clauses.append("department_id = ?")
            params.append(int(dept_id))
        sql = f"""
            SELECT AVG(
              (julianday(completed_at) - julianday(service_started_at)) * 24 * 60
            ) AS avg_min
            FROM   queue_tokens
            WHERE  {' AND '.join(clauses)}
        """
        cur = conn.execute(sql, params)
        row = cur.fetchone()
        val = None
        if row is not None:
            val = row[0] if not hasattr(row, "keys") else (row["avg_min"] if "avg_min" in row.keys() else row[0])
        if val is None:
            return 15.0
        v = float(val)
        if not np.isfinite(v) or v < 0:
            return 15.0
        return v
    except Exception:
        return 15.0


def build_wait_training(conn, days: int = 60) -> pd.DataFrame:
    """Build a training frame of completed queue tokens with features and actual wait.

    Args:
        conn: DB-API connection.
        days: Lookback window in days ending today.

    Returns:
        pd.DataFrame with one row per completed queue token and columns:
        ``patients_ahead`` (tokens created earlier in the same department with
        statuses Completed or Waiting, computed via window), ``avg_service``
        (rolling per-dept average of prior completed service minutes up to that
        row), ``dow`` (day of week of created_at, 0-6), ``hour`` (hour of
        created_at), and ``actual_wait`` (completed_at minus created_at,
        minutes). Empty frame returned on errors.
    """
    try:
        start = (date.today() - timedelta(days=max(1, days))).strftime("%Y-%m-%d 00:00:00")
        sql = """
            SELECT id, department_id, status, created_at, service_started_at, completed_at
            FROM   queue_tokens
            WHERE  created_at >= ?
            ORDER  BY department_id, created_at ASC
        """
        rows = pd.read_sql(sql, conn, params=[start])
        if rows.empty:
            return pd.DataFrame(columns=["patients_ahead", "avg_service", "dow", "hour", "actual_wait"])

        rows["created_at"] = pd.to_datetime(rows["created_at"], errors="coerce")
        rows["service_started_at"] = pd.to_datetime(rows["service_started_at"], errors="coerce")
        rows["completed_at"] = pd.to_datetime(rows["completed_at"], errors="coerce")
        rows = rows.dropna(subset=["created_at", "completed_at"]).copy()

        # Keep completed rows only as training samples.
        comp = rows.loc[rows["status"].astype(str).str.lower() == "completed"].copy()
        if comp.empty:
            return pd.DataFrame(columns=["patients_ahead", "avg_service", "dow", "hour", "actual_wait"])

        comp = comp.sort_values(["department_id", "created_at"]).reset_index(drop=True)

        # patients_ahead: count rows in the overall pool (waiting+completed) for same
        # dept with created_at strictly earlier.
        rows_by_dept: dict[Any, pd.DataFrame] = {
            dept: grp.reset_index(drop=True)
            for dept, grp in rows.groupby("department_id", sort=False)
        }

        patients_ahead_list: list[int] = []
        avg_service_list: list[float] = []
        dow_list: list[int] = []
        hour_list: list[int] = []
        actual_wait_list: list[float] = []

        global_fallback_avg = 15.0
        fallback_service_per_dept: dict[Any, float] = {}

        for _, r in comp.iterrows():
            dept = r["department_id"]
            pool = rows_by_dept.get(dept)
            ahead = 0
            if pool is not None:
                ahead = int((pool["created_at"] < r["created_at"]).sum())
            patients_ahead_list.append(max(0, ahead))

            # Actual wait in minutes.
            wait = (r["completed_at"] - r["created_at"]).total_seconds() / 60.0
            actual_wait_list.append(float(wait) if np.isfinite(wait) else 0.0)

            # Average service minutes for same dept, completed rows strictly earlier.
            earlier_comp = comp.loc[
                (comp["department_id"] == dept) & (comp["created_at"] < r["created_at"])
            ]
            if len(earlier_comp):
                svc = (
                    (earlier_comp["completed_at"] - earlier_comp["service_started_at"])
                    .dt.total_seconds() / 60.0
                )
                svc_valid = svc.replace([np.inf, -np.inf], np.nan).dropna()
                if len(svc_valid):
                    avg_val = float(svc_valid.mean())
                    if np.isfinite(avg_val) and avg_val > 0:
                        fallback_service_per_dept[dept] = avg_val
                        avg_service_list.append(avg_val)
                        dow_list.append(int(r["created_at"].dayofweek))
                        hour_list.append(int(r["created_at"].hour))
                        continue
            # Fallback to known dept avg, else global default.
            avg_service_list.append(float(fallback_service_per_dept.get(dept, global_fallback_avg)))
            dow_list.append(int(r["created_at"].dayofweek))
            hour_list.append(int(r["created_at"].hour))

        df = pd.DataFrame({
            "patients_ahead": patients_ahead_list,
            "avg_service": avg_service_list,
            "dow": dow_list,
            "hour": hour_list,
            "actual_wait": actual_wait_list,
        })
        # Ensure non-negative actual waits.
        df["actual_wait"] = df["actual_wait"].clip(lower=0.0)
        return df

    except Exception:
        return pd.DataFrame(columns=["patients_ahead", "avg_service", "dow", "hour", "actual_wait"])


def fit_linear_wait_adjustment(conn, days: int = 30, min_samples: int = 50
                               ) -> tuple[float, float, float, float] | None:
    """Train a small LinearRegression over the last ``days`` of completed waits.

    Public helper (not required by spec) that callers can use to obtain
    ``historical_coef`` for :func:`documented_estimate`. Returns None if the
    sample size is smaller than ``min_samples`` or training fails.

    Args:
        conn: DB-API connection.
        days: Lookback window passed to :func:`build_wait_training`.
        min_samples: Minimum number of completed tokens required (default 50).

    Returns:
        A 4-tuple ``(intercept, coef_baseline, coef_dow, coef_hour)``, or None.
    """
    try:
        if not _HAS_SKLEARN or _LinearRegression is None:
            return None
        df = build_wait_training(conn, days=days)
        if len(df) < max(1, min_samples):
            return None
        df = df.dropna().copy()
        if len(df) < max(1, min_samples):
            return None
        baseline = df["patients_ahead"].to_numpy(dtype=float) * df["avg_service"].to_numpy(dtype=float)
        X = np.column_stack([
            baseline,
            df["dow"].to_numpy(dtype=float),
            df["hour"].to_numpy(dtype=float),
        ])
        y = df["actual_wait"].to_numpy(dtype=float)
        mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
        X = X[mask]
        y = y[mask]
        if X.shape[0] < max(1, min_samples):
            return None
        lr = _LinearRegression()
        lr.fit(X, y)
        coefs = np.asarray(lr.coef_).ravel()
        c_base = float(coefs[0]) if len(coefs) > 0 else 1.0
        c_dow = float(coefs[1]) if len(coefs) > 1 else 0.0
        c_hour = float(coefs[2]) if len(coefs) > 2 else 0.0
        intercept = float(lr.intercept_)
        return intercept, c_base, c_dow, c_hour
    except Exception:
        return None
