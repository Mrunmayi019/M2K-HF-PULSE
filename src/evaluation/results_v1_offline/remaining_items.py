"""Remaining spreadsheet items: #3 (reference ranges), #3a (dose-response Spearman), #4a (R2),
#5 (severity-band split), #6a (leave-one-scenario-out), plus chart generation for #1 (PRISMA),
#4b (classifier feature importance), #5b (box plots). All offline, reuses the frozen model where
applicable; leave-one-scenario-out retrains in-memory ONLY, never writes to models/*.joblib.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.results_v1_offline.remaining_items
"""
from __future__ import annotations

import json
import pathlib

import joblib
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import r2_score

from src.analytics.risk_score import compute_risk_score
from src.scenario_classifier.features import build_features, feature_columns
from src.scenario_classifier.train import evaluate, split_patients

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
MODELS_DIR = REPO_ROOT / "models"
OUT_DIR = REPO_ROOT / "results" / "results_v1_offline"
FIG_DIR = OUT_DIR / "figures"
FEATURES_DATASET = REPO_ROOT / "data" / "simulation_runs" / "features_dataset.csv"
PATIENTS_CSV = REPO_ROOT / "data" / "synthetic" / "patients.csv"
TRENDS_CSV = REPO_ROOT / "data" / "synthetic" / "wearable_trends.csv"


def load_pulse_batch() -> pd.DataFrame:
    df = pd.read_csv(FEATURES_DATASET)
    rows = []
    for _, r in df.iterrows():
        score = compute_risk_score(
            hr_rise=r["hr_rise"], map_drop=r["map_drop"], co_drop_pct=r["co_drop_pct"],
            compensation_flag=int(r["compensation_flag"]), instability_flag=int(r["instability_flag"]),
            map_start=r["map_start"],
        )
        rows.append({**r.to_dict(), "risk_score": score["risk_score"], "risk_bucket": score["risk_bucket"]})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# #3: % of Pulse outputs within an established reference range. Only resting HR has a real,
# documented MIMIC-derived reference in this codebase (docs/data_provenance.md: inpatient HR
# mean 84.75, sd 15.06 -- explicitly kept as a "decompensated-state sanity ceiling", not a normal
# range). MAP/CO/SV have NO MIMIC-derived reference anywhere in this project -- not computed for
# those rather than inventing a textbook range the project has never cited.
# ---------------------------------------------------------------------------------------------
def reference_range_check(df: pd.DataFrame) -> dict:
    MIMIC_HR_MEAN, MIMIC_HR_SD = 84.75, 15.06
    ceiling = MIMIC_HR_MEAN + 2 * MIMIC_HR_SD  # 114.87 -- the documented "sanity ceiling"
    within = (df["hr_end"] <= ceiling).mean()
    by_scenario = df.groupby("scenario_type").apply(lambda g: (g["hr_end"] <= ceiling).mean())
    return {
        "metric": "hr_end <= MIMIC inpatient mean+2sd (84.75+2*15.06=114.87), the ONLY vital "
                  "with a documented MIMIC-derived reference in this project",
        "pct_within_overall": round(float(within) * 100, 1),
        "pct_within_by_scenario": {k: round(float(v) * 100, 1) for k, v in by_scenario.items()},
        "map_co_sv_not_computed_reason": "no MIMIC-derived reference range exists in this "
                                          "codebase for MAP, CO, or SV -- reference_stats.yaml "
                                          "has none, and inventing a generic clinical range "
                                          "would not be a documented-convention comparison.",
    }


# ---------------------------------------------------------------------------------------------
# #3a: dose-response, Spearman, severity vs cardiac output and stroke volume (the two the plan
# names specifically; row 20 already has Pearson on HR rise).
# ---------------------------------------------------------------------------------------------
def dose_response(df: pd.DataFrame) -> dict:
    out = {}
    for scenario in df["scenario_type"].unique():
        g = df[df["scenario_type"] == scenario]
        n = len(g)
        co_r, co_p = stats.spearmanr(g["severity"], g["co_drop_pct"])
        sv_r, sv_p = stats.spearmanr(g["severity"], g["stroke_volume_end"] / g["stroke_volume_start"])
        out[scenario] = {
            "n": n,
            "spearman_severity_vs_co_drop_pct": [round(co_r, 3), round(co_p, 4)],
            "spearman_severity_vs_sv_ratio": [round(sv_r, 3), round(sv_p, 4)],
        }
    return out


# ---------------------------------------------------------------------------------------------
# #4a: R^2 for the severity regressor, on train.py's own exact test split, frozen model.
# ---------------------------------------------------------------------------------------------
def regressor_r2() -> float:
    patients_df = pd.read_csv(PATIENTS_CSV)
    trends_df = pd.read_csv(TRENDS_CSV)
    features_df = build_features(patients_df, trends_df)
    cols = feature_columns(features_df)
    _, _, test_df = split_patients(features_df, seed=42)
    reg = joblib.load(MODELS_DIR / "severity_regressor.joblib")
    pred = reg.predict(test_df[cols])
    return round(float(r2_score(test_df["severity"], pred)), 4)


# ---------------------------------------------------------------------------------------------
# #5: severity-band (tertile) x scenario split of the Pulse batch's risk_score.
# ---------------------------------------------------------------------------------------------
def severity_band_split(df: pd.DataFrame) -> dict:
    bands = pd.qcut(df["severity"], 3, labels=["low", "mid", "high"])
    df = df.assign(severity_band=bands)
    out = {}
    for (scenario, band), g in df.groupby(["scenario_type", "severity_band"]):
        out.setdefault(scenario, {})[str(band)] = {
            "n": len(g), "mean_risk_score": round(float(g["risk_score"].mean()), 3),
            "severity_range": [round(float(g["severity"].min()), 3), round(float(g["severity"].max()), 3)],
        }
    return out


# ---------------------------------------------------------------------------------------------
# #6a: leave-one-scenario-out. Retrains IN MEMORY ONLY -- never writes to models/*.joblib.
# ---------------------------------------------------------------------------------------------
def leave_one_scenario_out() -> dict:
    patients_df = pd.read_csv(PATIENTS_CSV)
    trends_df = pd.read_csv(TRENDS_CSV)
    features_df = build_features(patients_df, trends_df)
    cols = feature_columns(features_df)
    scenarios = sorted(features_df["scenario_type"].unique())

    results = {}
    for held_out in scenarios:
        train_subset = features_df[features_df["scenario_type"] != held_out]
        held_out_rows = features_df[features_df["scenario_type"] == held_out]
        clf = RandomForestClassifier(n_estimators=300, max_depth=None, random_state=42, n_jobs=-1)
        clf.fit(train_subset[cols], train_subset["scenario_type"])
        preds = clf.predict(held_out_rows[cols])
        from collections import Counter
        results[held_out] = {
            "n_held_out": len(held_out_rows),
            "predicted_as": dict(Counter(preds)),
        }
    return results


def main():
    df = load_pulse_batch()

    results = {
        "reference_range_check": reference_range_check(df),
        "dose_response_spearman": dose_response(df),
        "regressor_r2": regressor_r2(),
        "severity_band_split": severity_band_split(df),
        "leave_one_scenario_out": leave_one_scenario_out(),
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "remaining_items.json", "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(json.dumps(results, indent=2, default=str))

    # --- Charts ---
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    # #4b: classifier feature importance
    clf = joblib.load(MODELS_DIR / "scenario_classifier.joblib")
    patients_df = pd.read_csv(PATIENTS_CSV)
    trends_df = pd.read_csv(TRENDS_CSV)
    features_df = build_features(patients_df, trends_df)
    cols = feature_columns(features_df)
    importances = pd.Series(clf.feature_importances_, index=cols).sort_values().tail(10)
    fig, ax = plt.subplots(figsize=(7, 5))
    importances.plot.barh(ax=ax, color="#2a78d6")
    ax.set_title("Scenario classifier -- top 10 feature importances")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "classifier_feature_importance.png", dpi=300)
    plt.close(fig)

    # #5b: box plots, risk score per scenario
    fig, ax = plt.subplots(figsize=(8, 5))
    order = ["stable", "deconditioning", "fluid_overload", "cardiac_stress", "acute_deterioration"]
    data = [df[df["scenario_type"] == s]["risk_score"].values for s in order]
    ax.boxplot(data, tick_labels=order)
    ax.set_ylabel("risk_score")
    ax.set_title("Risk score by scenario type (n=117 Pulse batch)")
    plt.xticks(rotation=20, ha="right")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "risk_score_boxplot_by_scenario.png", dpi=300)
    plt.close(fig)

    # #1: PRISMA-style flow diagram (counts from the spreadsheet's own 1a-1d rows, not re-derived)
    fig, ax = plt.subplots(figsize=(9, 7))
    ax.axis("off")
    boxes = [
        (0.5, 0.95, "PerHeart: 27 real patients"),
        (0.5, 0.82, "16 eligible (>=21 overlapping real days)\n11 excluded: < 21 overlapping real days"),
        (0.5, 0.69, "13/16 completed (81%)\n3 excluded: Pulse engine crash\n(user 6, 18, 22)"),
        (0.15, 0.50, "MIMIC: 17,129 admissions\n(outcome cohort)"),
        (0.85, 0.50, "MIMIC: 11,837 admissions\n(reference-stats cohort)"),
        (0.5, 0.35, "Pulse batch: 150 planned"),
        (0.5, 0.22, "117/150 completed (78%)\n33 excluded: engine crash/timeout\n(concentrated above severity ~0.45-0.6)"),
        (0.5, 0.08, "Synthetic: 2,000 patients generated\n1,400/300/300 train/val/test split"),
    ]
    for x, y, text in boxes:
        ax.text(x, y, text, ha="center", va="center", fontsize=9,
                 bbox=dict(boxstyle="round,pad=0.4", facecolor="#eaf1fb", edgecolor="#2a78d6"))
    for (x1, y1, _), (x2, y2, _) in [(boxes[0], boxes[1]), (boxes[1], boxes[2])]:
        ax.annotate("", xy=(x2, y2 + 0.045), xytext=(x1, y1 - 0.045),
                     arrowprops=dict(arrowstyle="->", color="#52514e"))
    for (x1, y1, _), (x2, y2, _) in [(boxes[5], boxes[6]), (boxes[6], boxes[7])]:
        ax.annotate("", xy=(x2, y2 + 0.045), xytext=(x1, y1 - 0.045),
                     arrowprops=dict(arrowstyle="->", color="#52514e"))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Data and cohort flow (not clinical PRISMA -- cohort/record accounting only)")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "data_cohort_flow.png", dpi=300)
    plt.close(fig)

    print("\nCharts written to", FIG_DIR)


if __name__ == "__main__":
    main()
