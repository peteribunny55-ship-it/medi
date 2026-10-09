from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd

try:
    import plotly.graph_objects as _go
    _HAS_PLOTLY = True
except Exception:
    _HAS_PLOTLY = False
    _go = None

try:
    from sklearn.ensemble import RandomForestRegressor as _RandomForestRegressor
    from sklearn.linear_model import LinearRegression as _LinearRegression
    from sklearn.metrics import mean_absolute_error as _mae, mean_squared_error as _mse, r2_score as _r2
    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False
    _RandomForestRegressor = None
    _LinearRegression = None
    _mae = _mse = _r2 = None


DEMO_NOTE = "DEMO ESTIMATES on SYNTHETIC DATA — NOT clinical or operational guarantees."


def build_demand_history(conn, dept_id: int | None = None, days: int = 120) -> pd.DataFrame:
    """Read and aggregate daily demand from the appointment_daily_demand table.

    Args:
        conn: SQLite connection object (or compatible DB-API connection).
        dept_id: Optional department id to filter rows. If None, sums demand across
            all departments per date (grouping by date when seed rows are per-dept).
        days: Lookback window in days ending today.

    Returns:
        pd.DataFrame with columns: date (datetime64[ns]), n_admissions, n_appointments,
        n_emergency, total_demand. Rows are sorted ascending by date. Missing dates in
        the window are filled with zeros so downstream rolling features behave.
    """
    try:
        end = pd.Timestamp(date.today()).normalize()
        start = end - timedelta(days=max(1, days) - 1)

        clauses: list[str] = ["date(demand_date) >= date(?)", "date(demand_date) <= date(?)"]
        params: list[Any] = [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")]
        if dept_id is not None:
            clauses.append("department_id = ?")
            params.append(dept_id)

        sql = f"""
            SELECT date(demand_date) AS demand_date,
                   department_id,
                   COALESCE(SUM(n_admissions), 0)   AS n_admissions,
                   COALESCE(SUM(n_appointments), 0) AS n_appointments,
                   COALESCE(SUM(n_emergency), 0)    AS n_emergency,
                   COALESCE(SUM(total_demand), 0)   AS total_demand
            FROM   appointment_daily_demand
            WHERE  {' AND '.join(clauses)}
            GROUP  BY date(demand_date){'' if dept_id is not None else ', department_id'}
        """
        raw = pd.read_sql(sql, conn, params=params)

        if raw.empty:
            full = pd.DataFrame({
                "date": pd.date_range(start, end, freq="D"),
                "n_admissions": 0,
                "n_appointments": 0,
                "n_emergency": 0,
                "total_demand": 0,
            })
            return full

        raw["demand_date"] = pd.to_datetime(raw["demand_date"])

        agg = (
            raw.groupby("demand_date", as_index=False)[
                ["n_admissions", "n_appointments", "n_emergency", "total_demand"]
            ]
            .sum()
            .rename(columns={"demand_date": "date"})
        )

        full_idx = pd.date_range(start, end, freq="D", name="date")
        full = agg.set_index("date").reindex(full_idx, fill_value=0).reset_index()
        return full.sort_values("date").reset_index(drop=True)

    except Exception as exc:
        _ = exc
        end = pd.Timestamp(date.today()).normalize()
        start = end - timedelta(days=max(1, days) - 1)
        return pd.DataFrame({
            "date": pd.date_range(start, end, freq="D"),
            "n_admissions": 0,
            "n_appointments": 0,
            "n_emergency": 0,
            "total_demand": 0,
        })


def add_features(df: pd.DataFrame, holidays: list[str] | None = None) -> pd.DataFrame:
    """Add calendar and rolling features to a demand DataFrame.

    Args:
        df: DataFrame with at least columns ``date`` (datetime-like) and
            ``total_demand`` (numeric). Typically the output of
            :func:`build_demand_history`.
        holidays: Optional list of "MM-DD" strings that should be marked as
            holidays (e.g. ``['01-01', '12-25']``).

    Returns:
        A new DataFrame with additional columns:
        dow (0-6), month (1-12), is_weekend (0/1), dom (day of month),
        week (ISO week of year), rolling_mean_7, rolling_mean_14, holiday_flag.
        Rolling means are forward-filled then any remaining NaN filled with the
        overall mean of ``total_demand``.
    """
    try:
        out = df.copy()
        out["date"] = pd.to_datetime(out["date"])
        out = out.sort_values("date").reset_index(drop=True)

        out["dow"] = out["date"].dt.dayofweek
        out["month"] = out["date"].dt.month
        out["is_weekend"] = (out["dow"] >= 5).astype(int)
        out["dom"] = out["date"].dt.day
        out["week"] = out["date"].dt.isocalendar().week.astype(int)

        out["rolling_mean_7"] = (
            out["total_demand"].rolling(window=7, min_periods=1).mean().ffill()
        )
        out["rolling_mean_14"] = (
            out["total_demand"].rolling(window=14, min_periods=1).mean().ffill()
        )

        overall_mean = float(pd.Series(out["total_demand"]).replace([np.inf, -np.inf], np.nan).mean())
        if np.isnan(overall_mean):
            overall_mean = 0.0

        out["rolling_mean_7"] = out["rolling_mean_7"].fillna(overall_mean)
        out["rolling_mean_14"] = out["rolling_mean_14"].fillna(overall_mean)

        hols = {h.strip() for h in (holidays or []) if h and isinstance(h, str)}
        mmdd = out["date"].dt.strftime("%m-%d")
        out["holiday_flag"] = mmdd.isin(hols).astype(int)

        return out

    except Exception:
        return df.copy()


def _feature_cols() -> list[str]:
    return [
        "dow", "month", "is_weekend", "dom", "week",
        "rolling_mean_7", "rolling_mean_14", "holiday_flag",
        "n_admissions", "n_appointments", "n_emergency",
    ]


def _seasonal_naive_predict(train_demand: pd.Series, train_dates: pd.Series,
                            target_dates: pd.Series) -> np.ndarray:
    """Predict each holdout/future row as the mean of same-DOW values in the last 4 available weeks."""
    train = pd.DataFrame({"date": pd.to_datetime(train_dates).reset_index(drop=True),
                          "y": train_demand.reset_index(drop=True)})
    preds: list[float] = []
    for d in pd.to_datetime(target_dates):
        dow_mask = train["date"].dt.dayofweek == int(d.dayofweek)
        before = train.loc[dow_mask & (train["date"] < d), "y"]
        last4 = before.tail(4)
        if len(last4) == 0:
            fallback = float(train["y"].tail(14).mean()) if len(train) else 0.0
            preds.append(0.0 if np.isnan(fallback) else fallback)
        else:
            val = float(last4.mean())
            preds.append(0.0 if np.isnan(val) else val)
    return np.asarray(preds, dtype=float)


def _safe_score(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float, float]:
    mask = np.isfinite(y_true) & np.isfinite(y_pred)
    if mask.sum() < 2:
        return float("nan"), float("nan"), float("nan")
    yt = y_true[mask]
    yp = y_pred[mask]
    if not _HAS_SKLEARN or _mae is None:
        mae = float(np.mean(np.abs(yt - yp)))
        rmse = float(np.sqrt(np.mean((yt - yp) ** 2)))
        ss_res = float(np.sum((yt - yp) ** 2))
        ss_tot = float(np.sum((yt - np.mean(yt)) ** 2))
        r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        return mae, rmse, r2
    mae = float(_mae(yt, yp))
    rmse = float(np.sqrt(_mse(yt, yp)))
    r2 = float(_r2(yt, yp))
    return mae, rmse, r2


def _build_future_frame(train_end: pd.Timestamp, horizon: int, holidays: list[str] | None,
                        historical: pd.DataFrame) -> pd.DataFrame:
    future_dates = pd.date_range(train_end + timedelta(days=1), periods=horizon, freq="D")
    frame = pd.DataFrame({"date": future_dates})
    frame["n_admissions"] = np.nan
    frame["n_appointments"] = np.nan
    frame["n_emergency"] = np.nan
    frame["total_demand"] = np.nan
    # Concatenate with history to compute rolling means, then slice back.
    hist_subset = historical[["date", "total_demand", "n_admissions", "n_appointments", "n_emergency"]].copy()
    combined = pd.concat([hist_subset, frame[["date", "total_demand", "n_admissions", "n_appointments", "n_emergency"]]],
                         ignore_index=True)
    combined["total_demand"] = pd.to_numeric(combined["total_demand"], errors="coerce")
    combined["rolling_mean_7"] = (
        combined["total_demand"].rolling(window=7, min_periods=1).mean().ffill()
    )
    combined["rolling_mean_14"] = (
        combined["total_demand"].rolling(window=14, min_periods=1).mean().ffill()
    )
    overall_mean = float(hist_subset["total_demand"].mean()) if len(hist_subset) else 0.0
    if np.isnan(overall_mean):
        overall_mean = 0.0
    combined["rolling_mean_7"] = combined["rolling_mean_7"].fillna(overall_mean)
    combined["rolling_mean_14"] = combined["rolling_mean_14"].fillna(overall_mean)
    # Calendar features.
    combined["date"] = pd.to_datetime(combined["date"])
    combined["dow"] = combined["date"].dt.dayofweek
    combined["month"] = combined["date"].dt.month
    combined["is_weekend"] = (combined["dow"] >= 5).astype(int)
    combined["dom"] = combined["date"].dt.day
    combined["week"] = combined["date"].dt.isocalendar().week.astype(int)
    hols = {h.strip() for h in (holidays or []) if h and isinstance(h, str)}
    combined["holiday_flag"] = combined["date"].dt.strftime("%m-%d").isin(hols).astype(int)
    # Forward-fill admissions/appointments/emergency with historical means for features.
    for col in ["n_admissions", "n_appointments", "n_emergency"]:
        col_mean = float(hist_subset[col].mean()) if len(hist_subset) and col in hist_subset else 0.0
        if np.isnan(col_mean):
            col_mean = 0.0
        combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(col_mean)
    future_only = combined.tail(horizon).reset_index(drop=True)
    return future_only


def train_forecast_model(df: pd.DataFrame, horizon: int = 7, dept_id: int | None = None,
                         holidays: list[str] | None = None) -> tuple[str, Any, dict, pd.DataFrame, pd.DataFrame]:
    """Train LinearRegression + RandomForest, compare with SeasonalNaive baseline, return best.

    Args:
        df: DataFrame with a datetime ``date`` column and numeric demand columns.
            Usually the output of :func:`add_features`.
        horizon: Number of future days to produce predictions for.
        dept_id: Optional department id (used only for provenance / notes).
        holidays: Optional list of "MM-DD" holiday markers forwarded to feature building.

    Returns:
        Tuple of (best_model_name, best_model_or_None, metrics_dict, future_df,
        holdout_df). ``holdout_df`` includes the last 14 rows with a ``predicted``
        column. ``future_df`` includes ``horizon`` rows past the training window
        with ``total_demand`` populated by the best model (or baseline).
    """
    try:
        work = df.copy()
        if "dow" not in work.columns:
            work = add_features(work, holidays=holidays)
        work["date"] = pd.to_datetime(work["date"])
        work = work.sort_values("date").reset_index(drop=True)

        n_rows = len(work)
        holdout_size = min(14, max(0, n_rows - 1))
        train_size = max(0, n_rows - holdout_size)

        metrics: dict[str, Any] = {
            "model": "SeasonalNaive",
            "MAE": None,
            "RMSE": None,
            "R2": None,
            "baseline_MAE": None,
            "n_train": int(train_size),
            "n_holdout": int(holdout_size),
            "horizon": int(horizon),
            "dept_id": dept_id,
            "note": DEMO_NOTE,
        }

        train_end = pd.Timestamp(work["date"].max() or pd.Timestamp(date.today()))
        future_df = _build_future_frame(train_end, max(1, horizon), holidays, work)
        holdout_df = work.iloc[train_size:].copy() if holdout_size > 0 else pd.DataFrame()

        if n_rows < 30:
            metrics["note"] = (
                f"{DEMO_NOTE} Insufficient training rows ({n_rows} < 30); "
                "returning SeasonalNaive baseline only."
            )
            if len(holdout_df):
                base_hold = _seasonal_naive_predict(
                    work.iloc[:train_size]["total_demand"],
                    work.iloc[:train_size]["date"],
                    holdout_df["date"],
                )
                holdout_df["predicted"] = base_hold
                bmae, brmse, br2 = _safe_score(
                    holdout_df["total_demand"].to_numpy(dtype=float), base_hold
                )
                metrics["baseline_MAE"] = bmae
                metrics["MAE"] = bmae
                metrics["RMSE"] = brmse
                metrics["R2"] = br2
            base_future = _seasonal_naive_predict(
                work["total_demand"], work["date"], future_df["date"]
            )
            future_df["total_demand"] = base_future
            return "SeasonalNaive", None, metrics, future_df, holdout_df

        train_df = work.iloc[:train_size].copy()
        holdout_df = work.iloc[train_size:].copy()

        feature_cols = [c for c in _feature_cols() if c in train_df.columns]
        target_col = "total_demand"

        X_train = train_df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        y_train = pd.to_numeric(train_df[target_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        X_hold = holdout_df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        y_hold = pd.to_numeric(holdout_df[target_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)

        baseline_pred = _seasonal_naive_predict(
            train_df[target_col], train_df["date"], holdout_df["date"]
        )
        baseline_mae, baseline_rmse, baseline_r2 = _safe_score(y_hold, baseline_pred)
        metrics["baseline_MAE"] = baseline_mae

        model_results: list[tuple[str, Any, float, float, float, np.ndarray]] = []
        model_results.append(("SeasonalNaive", None, baseline_mae, baseline_rmse, baseline_r2, baseline_pred))

        if _HAS_SKLEARN and _LinearRegression is not None:
            try:
                lr = _LinearRegression()
                lr.fit(X_train, y_train)
                lr_pred = np.asarray(lr.predict(X_hold), dtype=float)
                mae, rmse, r2 = _safe_score(y_hold, lr_pred)
                if np.isfinite(mae):
                    model_results.append(("LinearRegression", lr, mae, rmse, r2, lr_pred))
            except Exception:
                pass

        if _HAS_SKLEARN and _RandomForestRegressor is not None:
            try:
                rf = _RandomForestRegressor(n_estimators=80, max_depth=7, random_state=42, n_jobs=1)
                rf.fit(X_train, y_train)
                rf_pred = np.asarray(rf.predict(X_hold), dtype=float)
                mae, rmse, r2 = _safe_score(y_hold, rf_pred)
                if np.isfinite(mae):
                    model_results.append(("RandomForestRegressor", rf, mae, rmse, r2, rf_pred))
            except Exception:
                pass

        best = min(model_results, key=lambda r: (np.isnan(r[2]), r[2] if np.isfinite(r[2]) else 1e18))
        best_name, best_model, best_mae, best_rmse, best_r2, best_hold_pred = best

        holdout_df["predicted"] = best_hold_pred
        metrics["model"] = best_name
        metrics["MAE"] = best_mae
        metrics["RMSE"] = best_rmse
        metrics["R2"] = best_r2

        # Predict future using best model; if best is baseline or model fails, use seasonal naive.
        future_feats = future_df[feature_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
        if best_model is not None:
            try:
                future_pred = np.asarray(best_model.predict(future_feats), dtype=float)
                future_pred = np.where(np.isfinite(future_pred), future_pred, 0.0)
            except Exception:
                future_pred = _seasonal_naive_predict(work["total_demand"], work["date"], future_df["date"])
        else:
            future_pred = _seasonal_naive_predict(work["total_demand"], work["date"], future_df["date"])

        future_df["total_demand"] = future_pred
        return best_name, best_model, metrics, future_df, holdout_df

    except Exception as exc:
        # Ultra-safe fallback: return baseline with synthetic empty frames.
        _ = exc
        train_end = pd.Timestamp(getattr(df, "empty", True) or True and date.today())
        if len(df):
            try:
                train_end = pd.Timestamp(pd.to_datetime(df["date"]).max())
            except Exception:
                train_end = pd.Timestamp(date.today())
        future_df = _build_future_frame(train_end, max(1, horizon), holidays,
                                        df if len(df) else pd.DataFrame({"date": [train_end], "total_demand": [0]}))
        try:
            future_pred = _seasonal_naive_predict(df["total_demand"], df["date"], future_df["date"]) if len(df) else np.zeros(len(future_df))
        except Exception:
            future_pred = np.zeros(len(future_df))
        future_df["total_demand"] = future_pred
        holdout_df = df.tail(min(14, len(df))).copy() if len(df) else pd.DataFrame()
        if len(holdout_df):
            holdout_df["predicted"] = holdout_df.get("total_demand", pd.Series([0] * len(holdout_df))).to_numpy()
        metrics = {
            "model": "SeasonalNaive",
            "MAE": None,
            "RMSE": None,
            "R2": None,
            "baseline_MAE": None,
            "n_train": 0,
            "n_holdout": 0,
            "horizon": int(horizon),
            "dept_id": dept_id,
            "note": f"{DEMO_NOTE} Training failed; returning baseline fallback. Error: {type(exc).__name__}",
        }
        return "SeasonalNaive", None, metrics, future_df, holdout_df


def save_forecast(conn, model_name: str, metrics: dict, pred_df: pd.DataFrame,
                  dept_id: int | None = None) -> None:
    """Persist a forecast run into the forecast_history table.

    Args:
        conn: SQLite (or DB-API) connection.
        model_name: Short identifier of the chosen model (e.g. 'RandomForestRegressor').
        metrics: Dictionary of metrics produced by :func:`train_forecast_model`.
        pred_df: DataFrame of forecasted values (``future_df`` output).
        dept_id: Optional department id to attach to the row.
    """
    try:
        horizon_days = int(len(pred_df))
        today_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        metrics_safe = {}
        for k, v in (metrics or {}).items():
            if isinstance(v, (np.floating,)):
                metrics_safe[k] = float(v) if np.isfinite(v) else None
            elif isinstance(v, (np.integer,)):
                metrics_safe[k] = int(v)
            elif isinstance(v, np.ndarray):
                metrics_safe[k] = v.tolist()
            else:
                metrics_safe[k] = v
        preds_records: list[dict] = []
        for rec in (pred_df.to_dict(orient="records") if pred_df is not None and len(pred_df) else []):
            safe_rec: dict = {}
            for k, v in rec.items():
                if isinstance(v, (pd.Timestamp, datetime)):
                    safe_rec[k] = v.strftime("%Y-%m-%d %H:%M:%S")
                elif isinstance(v, (np.floating,)):
                    safe_rec[k] = float(v) if np.isfinite(v) else None
                elif isinstance(v, (np.integer,)):
                    safe_rec[k] = int(v)
                else:
                    safe_rec[k] = v
            preds_records.append(safe_rec)

        insert_sql = """
            INSERT INTO forecast_history
                (forecast_date, horizon_days, model_name, metrics_json,
                 predictions_json, department_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            today_str,
            horizon_days,
            str(model_name or "SeasonalNaive"),
            json.dumps(metrics_safe, default=str),
            json.dumps(preds_records, default=str),
            int(dept_id) if dept_id is not None else None,
        )
        conn.execute(insert_sql, params)
        try:
            conn.commit()
        except Exception:
            pass
    except Exception:
        # Silently swallow persistence errors so callers can rely on forecasts.
        return


def plot_forecast(train_df: pd.DataFrame, holdout_df: pd.DataFrame | None = None,
                  future_df: pd.DataFrame | None = None,
                  model_name: str | None = None,
                  metrics: dict | None = None):
    """Return a plotly figure overlaying actuals, holdout predictions and future forecast.

    Args:
        train_df: Historical training demand with columns date and total_demand.
        holdout_df: Optional holdout DataFrame with date, total_demand (actual),
            and a ``predicted`` column.
        future_df: Optional future forecast DataFrame with date and total_demand.
        model_name: Optional model name included in the chart title.
        metrics: Optional metrics dict whose MAE/RMSE/R2 values are shown in the
            title.

    Returns:
        A ``plotly.graph_objects.Figure`` instance. Train actuals are plotted as
        a solid blue line, holdout actuals as a dashed red line, holdout
        predictions as an orange line, and future predictions as a dotted green
        line. A clear annotation warns the user that the chart is a DEMO
        ESTIMATE / AI PREDICTION and NOT guaranteed.
    """
    if not _HAS_PLOTLY or _go is None:
        raise ImportError(
            "plotly is required for plot_forecast. Install the requirements.txt "
            "dependencies (scikit-learn + plotly) before plotting."
        )
    fig = _go.Figure()

    title_parts = ["Hospital Demand Forecast"]
    if model_name:
        title_parts.append(f"Model: {model_name}")
    if metrics:
        bits = []
        for key in ("MAE", "RMSE", "R2"):
            v = metrics.get(key)
            if v is None or (isinstance(v, float) and not np.isfinite(v)):
                continue
            bits.append(f"{key}={v:.3f}" if isinstance(v, float) else f"{key}={v}")
        if bits:
            title_parts.append("(" + ", ".join(bits) + ")")
    title_parts.append(" — DEMO / SYNTHETIC DATA")
    fig.update_layout(title=" ".join(title_parts), xaxis_title="Date",
                      yaxis_title="Total daily demand",
                      template="plotly_white",
                      hovermode="x unified")

    if train_df is not None and len(train_df):
        t = train_df.copy()
        t["date"] = pd.to_datetime(t["date"])
        fig.add_trace(_go.Scatter(
            x=t["date"], y=pd.to_numeric(t["total_demand"], errors="coerce"),
            mode="lines", name="Train (actual)",
            line=dict(color="#1f77b4", width=2, dash="solid"),
        ))

    if holdout_df is not None and len(holdout_df):
        h = holdout_df.copy()
        h["date"] = pd.to_datetime(h["date"])
        fig.add_trace(_go.Scatter(
            x=h["date"], y=pd.to_numeric(h["total_demand"], errors="coerce"),
            mode="lines", name="Holdout (actual)",
            line=dict(color="#d62728", width=2, dash="dash"),
        ))
        if "predicted" in h.columns:
            fig.add_trace(_go.Scatter(
                x=h["date"], y=pd.to_numeric(h["predicted"], errors="coerce"),
                mode="lines", name="Holdout (predicted)",
                line=dict(color="#ff7f0e", width=2, dash="solid"),
            ))

    if future_df is not None and len(future_df):
        f = future_df.copy()
        f["date"] = pd.to_datetime(f["date"])
        fig.add_trace(_go.Scatter(
            x=f["date"], y=pd.to_numeric(f["total_demand"], errors="coerce"),
            mode="lines", name="Future (predicted)",
            line=dict(color="#2ca02c", width=3, dash="dot"),
        ))
        yvals = pd.to_numeric(f["total_demand"], errors="coerce").fillna(0.0)
        fig.add_trace(_go.Scatter(
            x=list(f["date"]) + list(f["date"][::-1]),
            y=list(yvals * 1.15) + list(yvals * 0.85)[::-1],
            fill="toself", fillcolor="rgba(44, 160, 44, 0.12)",
            line=dict(color="rgba(0,0,0,0)"), hoverinfo="skip",
            name="Uncertainty band (illustrative)",
        ))

    all_dates: list[pd.Timestamp] = []
    for d in [train_df, holdout_df, future_df]:
        if d is not None and len(d) and "date" in d.columns:
            try:
                all_dates.extend(pd.to_datetime(d["date"]).tolist())
            except Exception:
                pass
    if all_dates:
        mid_x = pd.Timestamp(np.median([pd.Timestamp(d).value for d in all_dates]))
        max_y = 0.0
        for d in [train_df, holdout_df, future_df]:
            if d is not None and len(d) and "total_demand" in d.columns:
                try:
                    yv = pd.to_numeric(d["total_demand"], errors="coerce").dropna()
                    if len(yv):
                        max_y = max(max_y, float(yv.max()))
                except Exception:
                    pass
        fig.add_annotation(
            x=mid_x, y=max_y * 1.05 if max_y else 1.0,
            text=("<b>⚠️ AI Prediction / Estimate — NOT Guaranteed</b><br>"
                  "<sub>DEMO ESTIMATES on SYNTHETIC DATA. For planning illustration only.</sub>"),
            showarrow=False, font=dict(color="#b22222", size=12),
            bgcolor="rgba(255, 243, 205, 0.95)", bordercolor="#b22222", borderwidth=1.2,
            align="center", xanchor="center",
        )
    return fig
