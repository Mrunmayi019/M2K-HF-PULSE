"""Results-plan items: PerHeart cohort table + flow diagram, physiological plausibility of the
saved Pulse batch, severity dose-response split by EF, and live projection tabulation. Offline
only -- reads committed artifacts, runs no Pulse, writes nothing outside results/results_v1_offline/.

  1. PerHeart: all 27 patients, eligible/excluded + reason, from docs/real_world_data_integration.md
     §5 (eligibility rule + the 16 eligible user_ids) and the latest replay
     (data/real_world_validation/20260817_141634/results.csv). Anything not recorded is written as
     "not recorded" -- the raw PerHeart files (data/raw/, gitignored) are not read here.
  2. Plausibility: share of hr_start/hr_end inside the ONLY ranges reference_stats.yaml defines for
     any of MAP / cardiac output / stroke volume / heart rate (two HR entries, mean +- 2 SD). MAP, CO
     and SV have no range in reference_stats.yaml and are reported as not computed.
  3. Dose response: Spearman(severity, end-of-run MAP / CO / SV / HR) by scenario_type, split by
     EF <= 40 vs EF > 40. Cells with n < 5 are not computed.
  4. Projections: 7/14/30-day projected risk for the three live-test patients
     (results/results_v1_offline/live_projection_inputs.json), flagged flat when risk_score does not
     change across horizons.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.results_v1_offline.cohort_plausibility_projection
"""
from __future__ import annotations

import json
import pathlib

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import yaml
from scipy import stats

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT_DIR = REPO_ROOT / "results" / "results_v1_offline"
FIG_DIR = OUT_DIR / "figures"
FEATURES = REPO_ROOT / "data" / "simulation_runs" / "features_dataset.csv"
FAILED = REPO_ROOT / "data" / "simulation_runs" / "failed_runs.csv"
REFERENCE_STATS = REPO_ROOT / "src" / "data_synthesis" / "reference_stats.yaml"
PERHEART_RUN = REPO_ROOT / "data" / "real_world_validation" / "20260817_141634" / "results.csv"
LIVE_PROJECTIONS = OUT_DIR / "live_projection_inputs.json"

PERHEART_N = 27
# docs/real_world_data_integration.md §5 -- the recorded eligible set (>= 21 overlapping real
# HR+SpO2+weight days, computed by scripts/perheart_real_data_replay.py eligible_patients()).
PERHEART_ELIGIBLE = [1, 2, 4, 5, 6, 15, 16, 17, 18, 19, 21, 22, 23, 24, 25, 27]
EXCLUSION_RULE = (
    "fewer than 21 overlapping real HR+SpO2+weight days (the sole eligibility rule, "
    "real_world_data_integration.md §5)"
)
OUTPUTS = {"MAP (mmHg)": "map_end", "cardiac output (mL/min)": "co_end",
           "stroke volume (mL)": "stroke_volume_end", "heart rate (bpm)": "hr_end"}
MIN_N = 5


def perheart_table() -> pd.DataFrame:
    run = pd.read_csv(PERHEART_RUN).sort_values("attempt").groupby("user_id").tail(1).set_index("user_id")
    rows = []
    for uid in range(1, PERHEART_N + 1):
        if uid not in PERHEART_ELIGIBLE:
            rows.append({"user_id": uid, "eligible": False, "exclusion_reason": EXCLUSION_RULE,
                         "overlapping_real_days": "not recorded", "age": "not recorded", "sex": "not recorded",
                         "replayed": False, "replay_status": "", "failure_reason": "",
                         "scenario_type": "", "risk_bucket": ""})
            continue
        r = run.loc[uid]
        failed = r["simulation_status"] != "complete"
        rows.append({"user_id": uid, "eligible": True, "exclusion_reason": "",
                     "overlapping_real_days": ">=21 (latest 21-day window replayed)",
                     "age": int(r["age"]), "sex": r["sex"], "replayed": True,
                     "replay_status": r["simulation_status"],
                     "failure_reason": ("Pulse engine crash: PulseScenarioDriver exited 1 (both attempts); "
                                        "root cause not recorded -- severity-shift hypothesis only, "
                                        "real_world_data_integration.md §8.4") if failed else "",
                     "scenario_type": "" if failed else r["scenario_type"],
                     "risk_bucket": "" if failed else r["risk_bucket"]})
    return pd.DataFrame(rows)


def flow_diagram(table: pd.DataFrame) -> None:
    n_elig = int(table.eligible.sum())
    n_ok = int((table.replay_status == "complete").sum())
    failed_ids = table.loc[table.replay_status == "failed", "user_id"].tolist()
    excluded_ids = table.loc[~table.eligible, "user_id"].tolist()
    boxes = [
        (0.5, 0.88, f"PerHeart Pilot Dataset: {PERHEART_N} real HF patients"),
        (0.5, 0.64, f"Eligible and replayed: {n_elig}\n(>=21 overlapping real HR+SpO2+weight days)"),
        (0.5, 0.40, f"Completed assessment: {n_ok}"),
    ]
    side = [
        (0.88, 0.76, f"Excluded: {len(excluded_ids)}\n<21 overlapping days\n(per-patient counts not recorded)\nuser_id {', '.join(map(str, excluded_ids))}"),
        (0.88, 0.52, f"Failed: {len(failed_ids)}\nPulse engine crash (exit 1)\nuser_id {', '.join(map(str, failed_ids))}"),
    ]
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.axis("off")
    for x, y, t in boxes:
        ax.text(x, y, t, ha="center", va="center", fontsize=10, bbox=dict(boxstyle="round", fc="#E8F1FB", ec="#2E5A88"))
    for x, y, t in side:
        ax.text(x, y, t, ha="center", va="center", fontsize=8.5, bbox=dict(boxstyle="round", fc="#FBEAEA", ec="#8B2E2E"))
    for (x0, y0), (x1, y1) in [((0.5, 0.83), (0.5, 0.70)), ((0.5, 0.58), (0.5, 0.45))]:
        ax.annotate("", xy=(x1, y1), xytext=(x0, y0), arrowprops=dict(arrowstyle="->"))
    for y in (0.76, 0.52):
        ax.annotate("", xy=(0.72, y), xytext=(0.5, y), arrowprops=dict(arrowstyle="->", color="#8B2E2E"))
    ax.set_title(f"PerHeart replay flow (run 20260817_141634): {PERHEART_N} in, {n_elig} replayed, {n_ok} completed")
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG_DIR / "perheart_flow.png", dpi=150, bbox_inches="tight")
    plt.close(fig)


def plausibility(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    ref = yaml.safe_load(REFERENCE_STATS.read_text())
    wb = ref["wearable_baseline"]
    ranges = {
        "resting_hr_bpm (assumed_default, source null)": (
            wb["resting_hr_bpm"]["mean"] - 2 * wb["resting_hr_bpm"]["sd"],
            wb["resting_hr_bpm"]["mean"] + 2 * wb["resting_hr_bpm"]["sd"]),
        "decompensated_hr_reference (mimic_bigquery_extract)": (
            wb["decompensated_hr_reference"]["mean"] - 2 * wb["decompensated_hr_reference"]["sd"],
            wb["decompensated_hr_reference"]["mean"] + 2 * wb["decompensated_hr_reference"]["sd"]),
    }
    rows = []
    for scen, g in list(df.groupby("scenario_type")) + [("ALL", df)]:
        for col in ("hr_start", "hr_end"):
            for name, (lo, hi) in ranges.items():
                rows.append({"scenario_type": scen, "value": col, "range": name,
                             "range_bpm": f"{lo:.1f}-{hi:.1f}", "n": len(g),
                             "pct_inside": round(100 * g[col].between(lo, hi).mean(), 1)})
        for out in ("MAP", "cardiac output", "stroke volume"):
            rows.append({"scenario_type": scen, "value": out, "range": "none in reference_stats.yaml",
                         "range_bpm": "", "n": len(g), "pct_inside": "not computed"})
    return pd.DataFrame(rows), {k: list(v) for k, v in ranges.items()}


def dose_response(df: pd.DataFrame) -> pd.DataFrame:
    df = df.assign(ef_group=df.ejection_fraction_pct.le(40).map({True: "EF<=40", False: "EF>40"}))
    rows = []
    for (scen, grp), g in df.groupby(["scenario_type", "ef_group"]):
        for label, col in OUTPUTS.items():
            if len(g) < MIN_N or g.severity.nunique() < 3:
                rows.append({"scenario_type": scen, "ef_group": grp, "output": label, "n": len(g),
                             "spearman_rho": "not computed (n<5)", "p_value": ""})
                continue
            rho, p = stats.spearmanr(g.severity, g[col])
            rows.append({"scenario_type": scen, "ef_group": grp, "output": label, "n": len(g),
                         "spearman_rho": round(float(rho), 3), "p_value": round(float(p), 4)})
    return pd.DataFrame(rows)


def projections() -> pd.DataFrame:
    live = json.loads(LIVE_PROJECTIONS.read_text())["patients"]
    rows = []
    for pid, p in live.items():
        risks = [p["risk_now"]] + [p["horizons"][h]["risk_score"] for h in ("7", "14", "30")]
        spread = max(risks) - min(risks)
        rows.append({
            "patient": pid, "ef_input": p["ef_input"], "trend": p["trend"], "scenario_type": p["scenario_type"],
            "risk_now": p["risk_now"], "risk_7d": risks[1], "risk_14d": risks[2], "risk_30d": risks[3],
            "bucket_now_to_30d": " / ".join([p["bucket_now"]] + [p["horizons"][h]["risk_bucket"] for h in ("7", "14", "30")]),
            "severity_now": round(p["severity_now"], 3), "severity_30d": round(p["horizons"]["30"]["projected_severity"], 3),
            "risk_change_0_to_30d": round(spread, 4),
            "verdict": "FLAT (identical risk at every horizon)" if spread == 0 else
                       ("near-flat (< 0.01 change, same bucket)" if spread < 0.01 else "changes"),
        })
    return pd.DataFrame(rows)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table = perheart_table()
    table.to_csv(OUT_DIR / "perheart_cohort_table.csv", index=False)
    flow_diagram(table)

    feats = pd.read_csv(FEATURES)
    plaus, ranges = plausibility(feats)
    plaus.to_csv(OUT_DIR / "plausibility_by_scenario.csv", index=False)
    dose = dose_response(feats)
    dose.to_csv(OUT_DIR / "dose_response_by_scenario_ef.csv", index=False)
    proj = projections()
    proj.to_csv(OUT_DIR / "live_projections.csv", index=False)

    summary = {
        "perheart": {"total": len(table), "eligible_replayed": int(table.eligible.sum()),
                     "completed": int((table.replay_status == "complete").sum()),
                     "failed_user_ids": table.loc[table.replay_status == "failed", "user_id"].tolist(),
                     "excluded_user_ids": table.loc[~table.eligible, "user_id"].tolist()},
        "plausibility_ranges_used": ranges,
        "batch_runs_with_outputs": len(feats),
        "batch_failed_rows_in_failed_runs_csv": int(len(pd.read_csv(FAILED))) if FAILED.exists() else None,
        "projection_verdicts": dict(zip(proj.patient, proj.verdict)),
    }
    (OUT_DIR / "cohort_plausibility_projection.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(plaus[plaus.value.isin(["hr_start", "hr_end"])].to_string(index=False))
    print(dose.to_string(index=False))
    print(proj.to_string(index=False))


if __name__ == "__main__":
    main()
