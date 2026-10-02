"""Reads results/scenario_tests/daily_results_*.csv (NEVER re-simulates) and produces every table
and figure results/scenario_tests/RESULTS.md references: the main per-patient table, group
results, false-alert rate, the scenario label table, per-patient timeline figures, the P10 signal-
ablation, the weight-rule baseline comparison, reliability stats, and the day-14-vs-day-21 diff.

Both the 21-day primary window and the day-14 snapshot (read from the same rows, never re-run)
are produced for every applicable item, per the pre-registered analysis plan
(results/scenario_tests/expected_outcomes.md).

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.analyze
"""
from __future__ import annotations

import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "results" / "scenario_tests"
FIGURES_DIR = RESULTS_DIR / "figures"
COHORT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"

# Validated colorblind-safe palette (dataviz skill, references/palette.md) -- light-mode values.
BLUE = "#2a78d6"
RED = "#e34948"
GRAY = "#52514e"
ORANGE = "#eb6834"

PRIMARY_DAYS = 21
SNAPSHOT_DAY = 14


def load_all_results() -> pd.DataFrame:
    frames = []
    for path in sorted(RESULTS_DIR.glob("daily_results_*_seed*.csv")):
        frames.append(pd.read_csv(path))
    if not frames:
        raise SystemExit(f"No daily_results_*.csv files found in {RESULTS_DIR}")
    df = pd.concat(frames, ignore_index=True)
    df["alert_flag"] = df["alert_flag"].astype(bool)
    return df


def patient_alerted_all_seeds(df: pd.DataFrame, patient_id: str, through_day: int) -> bool:
    sub = df[(df["patient_id"] == patient_id) & (df["day"] <= through_day)]
    per_seed = sub.groupby("seed")["alert_flag"].any()
    return bool(per_seed.all()) if len(per_seed) > 0 else False


def first_alert_day(df: pd.DataFrame, patient_id: str, seed: int, through_day: int):
    sub = df[(df["patient_id"] == patient_id) & (df["seed"] == seed) & (df["day"] <= through_day) & (df["alert_flag"])]
    if sub.empty:
        return None
    return int(sub["day"].min())


# ---------------------------------------------------------------------------------------------
# 1. Main table
# ---------------------------------------------------------------------------------------------
def build_main_table(df: pd.DataFrame, through_day: int) -> pd.DataFrame:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    rows = []
    for pid, cfg in cohort["patients"].items():
        sub = df[(df["patient_id"] == pid) & (df["day"] <= through_day)]
        if sub.empty:
            continue
        alerted = patient_alerted_all_seeds(df, pid, through_day)
        first_days = [first_alert_day(df, pid, s, through_day) for s in sorted(sub["seed"].unique())]
        first_days_valid = [d for d in first_days if d is not None]
        lead_time = None
        story_start_day = 1 if pid in ("P02", "P03", "P08", "P09", "P01") else 4
        if first_days_valid:
            lead_time = min(first_days_valid) - story_start_day
        peak_risk = sub["risk_score"].max()
        label_counts = sub.groupby("predicted_scenario")["predicted_scenario"].count()
        dominant_label = label_counts.idxmax() if not label_counts.empty else None
        alert_sources = sub.loc[sub["alert_flag"], "alert_source"].value_counts().to_dict()
        rows.append({
            "patient_id": pid, "story": cfg["story"], "expected_group": cfg["expected_group"],
            "alerted_all_seeds": alerted,
            "first_alert_day_by_seed": first_days,
            "lead_time_days": lead_time,
            "dominant_predicted_label": dominant_label,
            "peak_risk_score": round(peak_risk, 4) if pd.notna(peak_risk) else None,
            "consistency_across_seeds": "consistent" if len(set(d is None for d in first_days)) <= 1 else "disagreement",
            "alerts_by_source": alert_sources,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# 2. Group results
# ---------------------------------------------------------------------------------------------
def group_results(main_table: pd.DataFrame) -> dict:
    should_catch = main_table[main_table["expected_group"] == "should_catch"]
    should_quiet = main_table[main_table["expected_group"] == "should_stay_quiet"]
    edge = main_table[main_table["expected_group"] == "edge_case"]
    return {
        "should_catch_n": len(should_catch),
        "should_catch_caught": int(should_catch["alerted_all_seeds"].sum()),
        "should_quiet_n": len(should_quiet),
        "should_quiet_false_alerts": int(should_quiet["alerted_all_seeds"].sum()),
        "edge_cases": edge[["patient_id", "story", "alerted_all_seeds", "first_alert_day_by_seed"]].to_dict("records"),
    }


# ---------------------------------------------------------------------------------------------
# 3. False alerts per 100 patient-days + unstable_fallback count
# ---------------------------------------------------------------------------------------------
def false_alert_rate(df: pd.DataFrame, through_day: int) -> dict:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    quiet_ids = [pid for pid, c in cohort["patients"].items() if c["expected_group"] == "should_stay_quiet"]
    sub = df[(df["patient_id"].isin(quiet_ids)) & (df["day"] <= through_day)]
    total_patient_days = len(sub)
    false_alert_days = int(sub["alert_flag"].sum())
    rate_per_100 = (false_alert_days / total_patient_days * 100) if total_patient_days else 0.0
    unstable_fallback_count = int((df[df["day"] <= through_day]["alert_source"] == "unstable_fallback").sum())
    return {
        "quiet_group_patient_days": total_patient_days,
        "false_alert_days": false_alert_days,
        "false_alerts_per_100_patient_days": round(rate_per_100, 2),
        "total_unstable_fallback_alerts_whole_cohort": unstable_fallback_count,
    }


# ---------------------------------------------------------------------------------------------
# 4. Scenario label table: expected vs predicted
# ---------------------------------------------------------------------------------------------
EXPECTED_LABEL = {
    "P01": "stable", "P02": "stable", "P03": "stable", "P04": "fluid_overload",
    "P05": "deconditioning", "P06": "cardiac_stress", "P07": "acute_deterioration",
    "P08": "stable", "P09": "stable", "P10": "acute_deterioration",
}


def label_table(df: pd.DataFrame, through_day: int) -> pd.DataFrame:
    sub = df[df["day"] <= through_day]
    rows = []
    for pid, expected in EXPECTED_LABEL.items():
        patient_sub = sub[sub["patient_id"] == pid]
        counts = patient_sub["predicted_scenario"].value_counts().to_dict()
        dominant = patient_sub["predicted_scenario"].mode()
        dominant = dominant.iloc[0] if not dominant.empty else None
        rows.append({
            "patient_id": pid, "expected_label": expected, "dominant_predicted_label": dominant,
            "label_counts": counts, "match": dominant == expected,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# 5. Patient timeline figures
# ---------------------------------------------------------------------------------------------
def plot_patient_timeline(df: pd.DataFrame, patient_id: str, story: str):
    sub = df[df["patient_id"] == patient_id].copy()
    agg = sub.groupby("day")["risk_score"].agg(["mean", "min", "max"]).reset_index()

    fig, ax = plt.subplots(figsize=(8, 3.2), dpi=300)
    ax.fill_between(agg["day"], agg["min"], agg["max"], color=BLUE, alpha=0.18, linewidth=0, label="seed min-max")
    ax.plot(agg["day"], agg["mean"], color=BLUE, linewidth=2, marker="o", markersize=3, label="mean risk score")
    ax.axhline(0.15, color=RED, linestyle="--", linewidth=1.2, label="stable-range threshold (0.15)")
    ax.axvline(SNAPSHOT_DAY, color=GRAY, linestyle=":", linewidth=1, label="day 14 snapshot")

    events = (sub[["day", "event"]].dropna().drop_duplicates(subset="day"))
    for _, row in events.iterrows():
        ax.annotate(str(row["event"]), xy=(row["day"], 0), xytext=(row["day"], -0.08),
                     rotation=90, fontsize=6, color=ORANGE, ha="center", va="top",
                     annotation_clip=False)

    ax.set_xlim(1, PRIMARY_DAYS)
    ax.set_ylim(-0.12, max(1.0, agg["max"].max() * 1.1 if agg["max"].notna().any() else 1.0))
    ax.set_xlabel("Monitored day")
    ax.set_ylabel("Risk score")
    ax.set_title(f"{patient_id}: {story}", fontsize=10)
    ax.legend(loc="upper left", fontsize=6, frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    out = FIGURES_DIR / f"timeline_{patient_id}.png"
    fig.savefig(out, dpi=300)
    plt.close(fig)
    return out


# ---------------------------------------------------------------------------------------------
# 6. Signal ablation on P10
# ---------------------------------------------------------------------------------------------
def feature_importances() -> pd.DataFrame:
    """Top-10 feature importances for both the scenario classifier and the severity regressor --
    added per protocol_amendments.md (2026-10-03) to show plainly where weight (and every other
    wearable signal) ranks, connecting directly to the P02/P03 discussion (both stories are
    weight-driven with severity_target held flat -- how much the models can even respond to a
    weight-only signal depends on how much weight actually matters to them)."""
    import joblib
    clf = joblib.load(REPO_ROOT / "models" / "scenario_classifier.joblib")
    reg = joblib.load(REPO_ROOT / "models" / "severity_regressor.joblib")
    # Derive the real column order from build_inference_features() itself (dummy trend data, 21
    # distinct days so no vital's slope/delta is degenerate) rather than reconstructing it by
    # hand -- avoids any risk of silently mismatching the models' actual training column order.
    from src.scenario_classifier.features import build_inference_features, feature_columns
    dummy_trends = pd.DataFrame({
        "patient_id": ["X"] * 21, "day": list(range(21)),
        "resting_hr_bpm": np.linspace(70, 75, 21), "spo2_pct": np.linspace(97, 96, 21),
        "weight_kg": np.linspace(80, 81, 21), "steps_per_day": np.linspace(6000, 5000, 21),
        "sleep_hours": np.linspace(7, 6.5, 21), "hrv_rmssd_ms": np.linspace(35, 30, 21),
    })
    dummy_row = {"patient_id": "X", "age": 60, "sex": "Male", "bmi": 25.0,
                 "ejection_fraction_pct": 50.0, "nt_probnp_pg_ml": 200.0}
    dummy_feats = build_inference_features(dummy_row, dummy_trends)
    cols = feature_columns(dummy_feats)
    rows = []
    for model_name, model in (("scenario_classifier", clf), ("severity_regressor", reg)):
        importances = pd.Series(model.feature_importances_, index=cols).sort_values(ascending=False)
        for rank, (feat, imp) in enumerate(importances.head(10).items(), start=1):
            rows.append({"model": model_name, "rank": rank, "feature": feat, "importance": round(imp, 4)})
    return pd.DataFrame(rows)


def p10_ablation(df: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    import joblib
    from src.scenario_classifier.features import build_inference_features, feature_columns

    cohort = yaml.safe_load(COHORT_PATH.read_text())
    p10 = cohort["patients"]["P10"]
    demo = p10["demographics"]
    clin = p10["baseline_clinical_report"]
    bmi = demo["weight_kg"] / (demo["height_cm"] / 100.0) ** 2
    patient_row = {
        "patient_id": "P10", "age": demo["age"], "sex": demo["sex"], "bmi": bmi,
        "ejection_fraction_pct": clin["ejection_fraction_pct"], "nt_probnp_pg_ml": clin["nt_probnp_pg_ml"],
    }

    clf = joblib.load(REPO_ROOT / "models" / "scenario_classifier.joblib")
    reg = joblib.load(REPO_ROOT / "models" / "severity_regressor.joblib")

    sub = df[(df["patient_id"] == "P10") & (df["seed"] == seed)].sort_values("day")
    ablations = {
        "none": [],
        "weight_kg": [],
        "steps_per_day": [],
        "hrv_rmssd_ms": [],
    }
    col_map = {"weight_kg": "wearable_weight_kg", "steps_per_day": "wearable_steps_per_day", "hrv_rmssd_ms": "wearable_hrv_rmssd_ms"}

    for window_end in range(1, len(sub) + 1):
        window = sub.iloc[:window_end]
        trends_rows = []
        for i, (_, r) in enumerate(window.iterrows()):
            trends_rows.append({
                "patient_id": "P10", "day": i,
                "resting_hr_bpm": r["wearable_resting_hr_bpm"],
                "spo2_pct": r["wearable_spo2_pct"],
                "weight_kg": r["wearable_weight_kg"],
                "steps_per_day": r["wearable_steps_per_day"],
                "sleep_hours": r.get("wearable_sleep_hours", 7.0),
                "hrv_rmssd_ms": r["wearable_hrv_rmssd_ms"],
            })
        trends_df = pd.DataFrame(trends_rows)

        for ablation_name in ablations:
            t = trends_df.copy()
            if ablation_name != "none":
                vital = ablation_name
                t[vital] = t[vital].iloc[0]  # hold flat at day-1 value -- removes trend/slope signal
            feats = build_inference_features(patient_row, t)
            cols = feature_columns(feats)
            severity = float(reg.predict(feats[cols])[0])
            ablations[ablation_name].append(severity)

    rows = []
    for name, series in ablations.items():
        peak = max(series) if series else None
        first_above_02 = next((i + 1 for i, v in enumerate(series) if v > 0.20), None)
        rows.append({"ablation": name, "peak_predicted_severity": round(peak, 4) if peak else None,
                      "first_day_severity_above_0.20": first_above_02})
    result = pd.DataFrame(rows)
    base_peak = result.loc[result["ablation"] == "none", "peak_predicted_severity"].iloc[0]
    base_day = result.loc[result["ablation"] == "none", "first_day_severity_above_0.20"].iloc[0]
    result["delta_peak_vs_full"] = result["peak_predicted_severity"] - base_peak
    result["delta_first_alert_day_vs_full"] = result["first_day_severity_above_0.20"].apply(
        lambda d: (d - base_day) if (d is not None and base_day is not None) else None
    )
    return result


# ---------------------------------------------------------------------------------------------
# 7. Baseline: weight rule (>=2kg gain within 3 days)
# ---------------------------------------------------------------------------------------------
def weight_rule_baseline(df: pd.DataFrame, through_day: int) -> pd.DataFrame:
    rows = []
    for pid, g in df[df["day"] <= through_day].groupby("patient_id"):
        g = g.sort_values(["seed", "day"])
        triggered_any_seed = False
        first_trigger_day = None
        for seed, gs in g.groupby("seed"):
            weights = gs.set_index("day")["wearable_weight_kg"]
            for d in weights.index:
                window = weights[(weights.index >= d - 2) & (weights.index <= d)]
                if len(window) >= 2 and (window.max() - window.min()) >= 2.0:
                    triggered_any_seed = True
                    if first_trigger_day is None or d < first_trigger_day:
                        first_trigger_day = int(d)
                    break
        pipeline_alerted = patient_alerted_all_seeds(df, pid, through_day)
        rows.append({
            "patient_id": pid, "weight_rule_triggered": triggered_any_seed,
            "weight_rule_first_trigger_day": first_trigger_day,
            "pipeline_alerted_all_seeds": pipeline_alerted,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# 8. Reliability
# ---------------------------------------------------------------------------------------------
def reliability_stats(df: pd.DataFrame, through_day: int) -> pd.DataFrame:
    sub = df[df["day"] <= through_day]
    rows = []
    for (pid, seed), g in sub.groupby(["patient_id", "seed"]):
        completed = int((g["run_status"] == "complete").sum())
        failed = int((g["run_status"] == "failed").sum())
        failed_rows = g[g["run_status"] == "failed"]
        rows.append({
            "patient_id": pid, "seed": seed, "completed_days": completed, "failed_days": failed,
            "max_engine_lag_days": int(g["engine_lag_days"].max()),
            "failed_on_days": failed_rows["day"].tolist(),
            "failed_severity_injected": failed_rows["severity_injected"].round(3).tolist(),
            "mean_wall_time_s": round(g["wall_time_s"].mean(), 1),
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# 9. Day-14 vs day-21 differences
# ---------------------------------------------------------------------------------------------
def day14_vs_day21(main_21: pd.DataFrame, main_14: pd.DataFrame) -> pd.DataFrame:
    merged = main_21.merge(main_14, on="patient_id", suffixes=("_21", "_14"))
    diffs = merged[
        (merged["alerted_all_seeds_21"] != merged["alerted_all_seeds_14"])
        | (merged["dominant_predicted_label_21"] != merged["dominant_predicted_label_14"])
    ]
    return diffs[[
        "patient_id", "alerted_all_seeds_14", "alerted_all_seeds_21",
        "dominant_predicted_label_14", "dominant_predicted_label_21",
    ]]


def main():
    df = load_all_results()
    df.to_csv(RESULTS_DIR / "combined_daily_results.csv", index=False)

    main_21 = build_main_table(df, PRIMARY_DAYS)
    main_14 = build_main_table(df, SNAPSHOT_DAY)
    main_21.to_csv(RESULTS_DIR / "main_table_day21.csv", index=False)
    main_14.to_csv(RESULTS_DIR / "main_table_day14.csv", index=False)

    groups_21 = group_results(main_21)
    groups_14 = group_results(main_14)

    false_alerts_21 = false_alert_rate(df, PRIMARY_DAYS)
    false_alerts_14 = false_alert_rate(df, SNAPSHOT_DAY)

    labels_21 = label_table(df, PRIMARY_DAYS)
    labels_14 = label_table(df, SNAPSHOT_DAY)
    labels_21.to_csv(RESULTS_DIR / "label_table_day21.csv", index=False)
    labels_14.to_csv(RESULTS_DIR / "label_table_day14.csv", index=False)

    cohort = yaml.safe_load(COHORT_PATH.read_text())
    for pid, cfg in cohort["patients"].items():
        plot_patient_timeline(df, pid, cfg["story"])

    importances = feature_importances()
    importances.to_csv(RESULTS_DIR / "feature_importances.csv", index=False)

    ablation = p10_ablation(df)
    ablation.to_csv(RESULTS_DIR / "p10_ablation.csv", index=False)

    baseline_21 = weight_rule_baseline(df, PRIMARY_DAYS)
    baseline_21.to_csv(RESULTS_DIR / "weight_rule_baseline_day21.csv", index=False)

    reliability = reliability_stats(df, PRIMARY_DAYS)
    reliability.to_csv(RESULTS_DIR / "reliability.csv", index=False)

    diffs = day14_vs_day21(main_21, main_14)
    diffs.to_csv(RESULTS_DIR / "day14_vs_day21_diffs.csv", index=False)

    import json
    summary = {
        "groups_day21": groups_21, "groups_day14": groups_14,
        "false_alerts_day21": false_alerts_21, "false_alerts_day14": false_alerts_14,
    }
    with open(RESULTS_DIR / "analysis_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print("Analysis complete. Outputs in", RESULTS_DIR)
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
