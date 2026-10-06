"""Post-hoc analysis, requested 2026-10-03, kept entirely separate from the pre-registered
RESULTS.md / analyze.py outputs (which are UNCHANGED by this file).

Two things motivated this file:

1. Q1 finding: analyze.py's pre-registered "alert" (CSV column `alert_flag`) is
   `current_alert.get("alert") == "alert"` from the REAL `src.api.routes._build_status()` --
   i.e. `alert_decision()` in `src/analytics/score_reporting.py`, gated on
   `severity > STABLE_SEVERITY_CAP (0.15)` + a confidence floor. That machinery is real production
   code, but a full-repo grep (`current_alert|alert_basis|alert_decision|build_score_report`)
   shows it is consumed ONLY inside src/api/ itself -- no frontend component ever reads it.
   Every frontend component that shows risk/alert state (HeroStatusCard, SimulationLabPage,
   ReportsPage, DoctorReportCard, TrendsHistoryPage, Sidebar, ForwardProjectionPanel) reads
   `assessment.risk_bucket` instead, which comes from a DIFFERENT function
   (`src/analytics/risk_score.py::compute_risk_score()`, thresholds LOW_HIGH_BOUNDARY=0.35 /
   MODERATE_HIGH_BOUNDARY=0.65). **The dashboard a clinician actually sees alerts on
   `risk_bucket == "HIGH"` (risk_score >= 0.65); it never surfaces `alert_decision()`'s output at
   all.** This file recomputes every pre-registered headline number under that system-facing
   definition, from the exact same saved CSVs analyze.py already read -- no re-simulation.

2. Q4: three post-hoc alert-smoothing rules (R1/R2/R3, defined BEFORE this file existed --
   results/scenario_tests/posthoc_plan.md, committed separately) applied on top of the
   system-definition per-day alert signal.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.posthoc_analysis
"""
from __future__ import annotations

import json
import pathlib

import pandas as pd
import yaml

from src.evaluation.scenario_tests.analyze import (
    REPO_ROOT, RESULTS_DIR, COHORT_PATH, PRIMARY_DAYS, load_all_results,
)

POSTHOC_DIR = RESULTS_DIR / "posthoc"
POSTHOC_DIR.mkdir(parents=True, exist_ok=True)

RISK_HIGH_THRESHOLD = 0.65  # src/analytics/risk_score.py MODERATE_HIGH_BOUNDARY -- the real
                             # risk_bucket=="HIGH" cutoff the dashboard actually alerts on.


def add_system_alert_column(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["system_alert"] = df["risk_bucket"] == "HIGH"
    return df


# ---------------------------------------------------------------------------------------------
# Q1/Q3: headline numbers recomputed under the system's own (risk_bucket) alert definition.
# ---------------------------------------------------------------------------------------------
def alerted_all_seeds(df: pd.DataFrame, patient_id: str, alert_col: str, through_day: int):
    sub = df[(df["patient_id"] == patient_id) & (df["day"] <= through_day)]
    per_seed_first = []
    for seed, g in sub.groupby("seed"):
        g = g.sort_values("day")
        hit = g[g[alert_col]]
        per_seed_first.append(int(hit["day"].iloc[0]) if len(hit) else None)
    return all(d is not None for d in per_seed_first), per_seed_first


def main_table_system_def(df: pd.DataFrame, through_day: int) -> pd.DataFrame:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    rows = []
    for pid, cfg in cohort["patients"].items():
        alerted, firsts = alerted_all_seeds(df, pid, "system_alert", through_day)
        lead_time = None
        if alerted:
            story_start = next((d["day"] for d in cfg["monitored_day_schedule"] if d.get("event")), 1)
            lead_time = min(f - story_start for f in firsts)
        rows.append({
            "patient_id": pid, "story": cfg["story"], "expected_group": cfg["expected_group"],
            "alerted_all_seeds_system_def": alerted,
            "first_alert_day_by_seed_system_def": firsts,
            "lead_time_days_system_def": lead_time,
        })
    return pd.DataFrame(rows)


def false_alert_rate_system_def(df: pd.DataFrame, through_day: int) -> dict:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    quiet_ids = [pid for pid, c in cohort["patients"].items() if c["expected_group"] == "should_stay_quiet"]
    sub = df[(df["patient_id"].isin(quiet_ids)) & (df["day"] <= through_day)]
    total = len(sub)
    false_days = int(sub["system_alert"].sum())
    return {
        "quiet_group_patient_days": total,
        "false_alert_days_system_def": false_days,
        "false_alerts_per_100_patient_days_system_def": round(false_days / total * 100, 2) if total else 0.0,
    }


def weight_rule_vs_system_def(df: pd.DataFrame, through_day: int) -> pd.DataFrame:
    from src.evaluation.scenario_tests.analyze import weight_rule_baseline
    wr = weight_rule_baseline(df, through_day).set_index("patient_id")
    rows = []
    for pid in wr.index:
        alerted, _ = alerted_all_seeds(df, pid, "system_alert", through_day)
        rows.append({
            "patient_id": pid,
            "weight_rule_triggered": bool(wr.loc[pid, "weight_rule_triggered"]),
            "pipeline_alerted_all_seeds_system_def": alerted,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------
# Q4: post-hoc rules R1/R2/R3 (defined in posthoc_plan.md BEFORE this was run).
# ---------------------------------------------------------------------------------------------
def apply_rule(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Returns df with an added boolean column `rule_alert` per (patient, seed, day)."""
    df = df.sort_values(["patient_id", "seed", "day"]).copy()
    out = []
    for (pid, seed), g in df.groupby(["patient_id", "seed"]):
        g = g.sort_values("day").reset_index(drop=True)
        risk = g["risk_score"].astype(float)
        above = risk >= RISK_HIGH_THRESHOLD
        if rule == "baseline":
            g["rule_alert"] = above
        elif rule == "R1":
            g["rule_alert"] = above & above.shift(1, fill_value=False)
        elif rule == "R2":
            g["rule_alert"] = above & above.shift(1, fill_value=False) & above.shift(2, fill_value=False)
        elif rule == "R3":
            g["rule_alert"] = risk.rolling(3, min_periods=3).mean() >= RISK_HIGH_THRESHOLD
            g["rule_alert"] = g["rule_alert"].fillna(False)
        else:
            raise ValueError(rule)
        out.append(g)
    return pd.concat(out, ignore_index=True)


def evaluate_rule(df_with_rule: pd.DataFrame, through_day: int) -> dict:
    cohort = yaml.safe_load(COHORT_PATH.read_text())
    sub = df_with_rule[df_with_rule["day"] <= through_day]

    should_catch = [pid for pid, c in cohort["patients"].items() if c["expected_group"] == "should_catch"]
    quiet = [pid for pid, c in cohort["patients"].items() if c["expected_group"] == "should_stay_quiet"]

    caught = 0
    lead_times = []
    for pid in should_catch:
        alerted, firsts = alerted_all_seeds(sub, pid, "rule_alert", through_day)
        if alerted:
            caught += 1
            cfg = cohort["patients"][pid]
            story_start = next((d["day"] for d in cfg["monitored_day_schedule"] if d.get("event")), 1)
            lead_times.append(min(f - story_start for f in firsts))

    quiet_sub = sub[sub["patient_id"].isin(quiet)]
    total_quiet_days = len(quiet_sub)
    false_days = int(quiet_sub["rule_alert"].sum())

    return {
        "should_catch_detected": caught,
        "should_catch_total": len(should_catch),
        "mean_lead_time_days": round(sum(lead_times) / len(lead_times), 2) if lead_times else None,
        "false_alerts_per_100_patient_days": round(false_days / total_quiet_days * 100, 2) if total_quiet_days else 0.0,
    }


def main():
    df = load_all_results()
    df = add_system_alert_column(df)

    main_21 = main_table_system_def(df, PRIMARY_DAYS)
    main_21.to_csv(POSTHOC_DIR / "main_table_day21_system_def.csv", index=False)

    false_alerts_21 = false_alert_rate_system_def(df, PRIMARY_DAYS)

    weight_vs_system = weight_rule_vs_system_def(df, PRIMARY_DAYS)
    weight_vs_system.to_csv(POSTHOC_DIR / "weight_rule_vs_system_def_day21.csv", index=False)

    rule_results = {}
    for rule in ("baseline", "R1", "R2", "R3"):
        df_rule = apply_rule(df, rule)
        rule_results[rule] = evaluate_rule(df_rule, PRIMARY_DAYS)

    summary = {
        "false_alerts_day21_system_def": false_alerts_21,
        "rule_comparison": rule_results,
    }
    with open(POSTHOC_DIR / "posthoc_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(main_21.to_string())
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
