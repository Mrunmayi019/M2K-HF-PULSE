"""Builds config/scenario_tests/cohort_exp2.yaml -- the Experiment 2 cohort
(results/scenario_tests/exp2/PREREGISTRATION.md).

Same 10 patients, stories, demographics, baseline wearables, NT-proBNP and expected groups as
Experiment 1 (build_cohort.py, reused unmodified). Exactly three things differ:

  1. EF: every patient's baseline_ef_pct is +10 points (48-57% -> 58-67%), moving the cohort inside
     the training "stable" class's EF range (mean 61.2, 5th-95th percentile 54.9-67.5).
  2. P07: the acute onset moves from days 10-12 to days 4-6 (same 3-day ramp 0.20 -> 0.40, same
     step-count drop, then held at 0.40), so every should_catch story starts on day 4.
  3. meta: new seeds 48-53 (never used before) and warmup_days=1, which run_patient_seed.py reads to
     run one unscored warm-up day before monitored day 1.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.build_cohort_exp2
"""
from __future__ import annotations

import pathlib

import yaml

from src.evaluation.scenario_tests import build_cohort as exp1

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUTPUT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort_exp2.yaml"

EF_SHIFT_PCT = 10.0
SEEDS = [48, 49, 50, 51, 52, 53]
WARMUP_DAYS = 1
P07_ONSET_START, P07_ONSET_END = 4, 6


def schedule_p07_exp2(base):
    """schedule_p07 from build_cohort.py with the onset window moved from days 10-12 to days 4-6.
    Magnitudes, ramp length and the held plateau are unchanged."""
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    deltas = exp1.DELTAS_AT_SEVERITY_1["acute_deterioration"]
    start, end = P07_ONSET_START, P07_ONSET_END
    rows = []
    for d in range(1, exp1.MONITORED_DAYS + 1):
        if d < start:
            sev, event = 0.20, None
        elif d <= end:
            sev = 0.20 + (0.40 - 0.20) * (d - (start - 1)) / (end - (start - 1))
            event = "acute_onset"
        else:
            sev, event = 0.40, "acute_held"
        this_hr = hr + deltas["resting_hr_bpm"] * sev
        this_hrv = hrv + deltas["hrv_rmssd_ms"] * sev
        step_mult = exp1._ramp(d, start - 1, end, 1.0, 0.5)
        rows.append(exp1._day(d, sev, w, steps * step_mult * exp1._weekday_step_factor(d), this_hr, this_hrv, sleep, event=event))
    return rows


def build():
    cohort = exp1.build()
    meta = cohort["meta"]
    meta["experiment"] = 2
    meta["note"] = "Experiment 2 (results/scenario_tests/exp2/PREREGISTRATION.md). Built from build_cohort.py with EF +10, P07 onset days 4-6, seeds 48-53, 1 warm-up day."
    meta["results_tag"] = "v1.2"
    meta["seeds"] = SEEDS
    meta["warmup_days"] = WARMUP_DAYS
    for pid, cfg in cohort["patients"].items():
        cfg["baseline_clinical_report"]["ejection_fraction_pct"] += EF_SHIFT_PCT
    cohort["patients"]["P07"]["monitored_day_schedule"] = schedule_p07_exp2(exp1.PATIENTS["P07"]["baseline"])
    return cohort


def main():
    cohort = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        yaml.dump(cohort, f, default_flow_style=False, sort_keys=False, width=100)
    print(f"Wrote {OUTPUT_PATH} -- {len(cohort['patients'])} patients, seeds {SEEDS}")


if __name__ == "__main__":
    main()
