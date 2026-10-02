"""Builds config/scenario_tests/cohort.yaml: 10 hand-authored synthetic patients, each with an
explicit, reproducible day-by-day 21-monitored-day wearable/severity schedule implementing one
pre-registered story (results/scenario_tests/expected_outcomes.md).

Demographics are drawn from this project's own reference_stats.yaml ranges (docs/data_provenance.md)
-- no invented ranges. Day-by-day wearable deltas reuse generate_wearable_trends.py's own
SCENARIO_SIGNAL_DELTAS magnitudes as calibration anchors (same clinical-direction deltas-at-full-
severity the population generator uses), but applied with explicit per-day, per-patient control
(ramps, plateaus, discrete event days) that the population generator's whole-window curve can't
express -- this script IS the "day-by-day schedule", not a wrapper around the population generator.

`severity_target` is this story's INTENDED/injected severity for that day -- used only to scale
the wearable deltas below (what a patient at that severity plausibly reports). It is NOT written
directly into Pulse: the real pipeline's own classifier (run_daily_continuous_pipeline(), per the
project's run_assessment_pipeline()/continuous_state_pipeline.py architecture) independently
predicts scenario_type/severity from these wearable numbers, exactly as it would in production.
Any difference between severity_target and the classifier's own prediction is a real finding, not
an error -- see results/scenario_tests/RESULTS.md's label/severity comparison.

`input_level_only: true` on a field marks a wearable value this story deliberately did NOT pair
with a change in severity_target (P02's transient weight bump, P03's weight creep despite a flat
severity_target, and every patient's sleep/HRV dips from a "poor sleep" narrative event) --
documentation of intent for the analysis, not a technical Pulse-wiring distinction (no per-day
wearable field reaches Pulse directly in this architecture; only severity_target does, indirectly,
via the classifier).

Seeds (42/43/44) affect ONLY the small realistic day-to-day noise layer added at simulation time
(src/evaluation/scenario_tests/run_patient_seed.py) -- this script's own schedule is fully
deterministic and seed-independent, satisfying "one patient-seed per process" reproducibility.

Run: PYTHONPATH=. python3 -m src.evaluation.scenario_tests.build_cohort
"""
from __future__ import annotations

import datetime
import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
OUTPUT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort.yaml"

BASELINE_DAYS = 21
MONITORED_DAYS = 21
SEEDS = [42, 43, 44]

# Same per-vital clinical-direction magnitudes generate_wearable_trends.SCENARIO_SIGNAL_DELTAS
# uses (max deviation from baseline at severity=1.0) -- reused here as calibration anchors for
# this script's own explicit per-day deltas, not re-imported, since this script controls per-day
# shape (ramps/plateaus/events) the population generator's single whole-window curve cannot.
DELTAS_AT_SEVERITY_1 = {
    "fluid_overload": {"weight_kg": 4.5, "resting_hr_bpm": 12, "spo2_pct": -2.5, "steps_per_day": -1200, "sleep_hours": -0.8, "hrv_rmssd_ms": -6},
    "cardiac_stress": {"weight_kg": 0.5, "resting_hr_bpm": 20, "spo2_pct": -1.5, "steps_per_day": -1000, "sleep_hours": -0.5, "hrv_rmssd_ms": -12},
    "deconditioning": {"weight_kg": 1.0, "resting_hr_bpm": 8, "spo2_pct": -0.5, "steps_per_day": -2500, "sleep_hours": -0.3, "hrv_rmssd_ms": -5},
    "acute_deterioration": {"weight_kg": 3.0, "resting_hr_bpm": 25, "spo2_pct": -5.0, "steps_per_day": -2000, "sleep_hours": -1.2, "hrv_rmssd_ms": -15},
}


def _day(day, severity_target, weight_kg, steps_per_day, resting_hr_bpm, hrv_rmssd_ms, sleep_hours,
          event=None, weight_input_only=False, sleep_input_only=False):
    return {
        "day": day,
        "severity_target": round(severity_target, 4),
        "weight_kg": round(weight_kg, 2),
        "steps_per_day": round(steps_per_day),
        "resting_hr_bpm": round(resting_hr_bpm, 1),
        "hrv_rmssd_ms": round(hrv_rmssd_ms, 1),
        "sleep_hours": round(sleep_hours, 2),
        "event": event,
        "weight_input_level_only": weight_input_only,
        "sleep_input_level_only": sleep_input_only,
    }


def _weekday_step_factor(day: int) -> float:
    """Every 6th/7th day of the 21-day window reads as a lower-activity 'weekend' -- same
    weekday/weekend step variation real wearable data shows, independent of any story event."""
    return 0.82 if (day - 1) % 7 in (5, 6) else 1.0


# ---------------------------------------------------------------------------------------------
# P01 -- Stable patient, ordinary life. Normal variation only; severity_target 0.20 throughout.
# ---------------------------------------------------------------------------------------------
def schedule_p01(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    return [
        _day(d, 0.20, w, steps * _weekday_step_factor(d), hr, hrv, sleep)
        for d in range(1, MONITORED_DAYS + 1)
    ]


# ---------------------------------------------------------------------------------------------
# P02 -- Salty weekend (edge case). Days 5-7: weight +2.0kg (wearable only, severity flat).
# Days 8-10: returns to baseline. Severity_target 0.20 throughout.
# ---------------------------------------------------------------------------------------------
def schedule_p02(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        if 5 <= d <= 7:
            weight = w + 2.0
            event, w_only = "salty_weekend_peak", True
        elif 8 <= d <= 10:
            # linear return to baseline over days 8-10
            frac_back = (d - 7) / 3
            weight = (w + 2.0) - frac_back * 2.0
            event, w_only = "salty_weekend_recovery", True
        else:
            weight, event, w_only = w, None, False
        rows.append(_day(d, 0.20, weight, steps * _weekday_step_factor(d), hr, hrv, sleep,
                          event=event, weight_input_only=w_only))
    return rows


# ---------------------------------------------------------------------------------------------
# P03 -- Slow, quiet weight gain (edge case). Weight +0.3kg/day from day 4 to day 21, wearable
# only -- everything else normal, severity_target 0.20 throughout (flat, deliberately decoupled).
# ---------------------------------------------------------------------------------------------
def schedule_p03(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        if d >= 4:
            weight = w + 0.3 * (d - 3)
            event, w_only = "quiet_weight_creep", True
        else:
            weight, event, w_only = w, None, False
        rows.append(_day(d, 0.20, weight, steps * _weekday_step_factor(d), hr, hrv, sleep,
                          event=event, weight_input_only=w_only))
    return rows


# ---------------------------------------------------------------------------------------------
# P04 -- Fluid overload building up. Days 4-21: severity ramps 0.20->0.50 (reaches 0.50 only on
# day 21); weight +0.4kg/day from day 4; from day 10 steps fall ~30%; from day 14 poorer sleep
# (HR +5bpm, HRV -15%, sleep/HRV marked input_level_only -- the poor-sleep COMPONENT specifically,
# not the severity-tied weight/step/HR-congestion components).
# ---------------------------------------------------------------------------------------------
def schedule_p04(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    deltas = DELTAS_AT_SEVERITY_1["fluid_overload"]
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        if d < 4:
            sev = 0.20
        else:
            sev = 0.20 + (0.50 - 0.20) * (d - 4) / (21 - 4)  # linear 0.20 -> 0.50, day4..day21
        weight = w + (0.4 * max(d - 3, 0))  # independent of severity-scaled delta -- explicit "+0.4kg/day" story
        step_mult = 1.0
        if d >= 10:
            step_mult = 0.70  # ~30% fall, breathless
        this_hr = hr + deltas["resting_hr_bpm"] * sev
        this_hrv = hrv + deltas["hrv_rmssd_ms"] * sev
        poor_sleep = d >= 14
        if poor_sleep:
            this_hr += 5.0
            this_hrv -= this_hrv * 0.15  # -15% on top of already-reduced HRV
            this_sleep = sleep - 1.0
        else:
            this_sleep = sleep
        rows.append(_day(
            d, sev, weight, steps * step_mult * _weekday_step_factor(d), this_hr, this_hrv, this_sleep,
            event=("poor_sleep" if poor_sleep else ("breathless" if d >= 10 else ("fluid_ramp" if d >= 4 else None))),
            sleep_input_only=poor_sleep,
        ))
    return rows


# ---------------------------------------------------------------------------------------------
# P05 -- Gradual deconditioning. Steps fall step-by-step: -20% days 4-9, -40% days 10-15,
# -60% days 16-21; resting HR drifts up slowly; severity_target 0.20->0.35 over days 4-21.
# ---------------------------------------------------------------------------------------------
def schedule_p05(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    deltas = DELTAS_AT_SEVERITY_1["deconditioning"]
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        if d < 4:
            sev, step_mult, event = 0.20, 1.0, None
        else:
            sev = 0.20 + (0.35 - 0.20) * (d - 4) / (21 - 4)
            if d <= 9:
                step_mult, event = 0.80, "steps_down_20pct"
            elif d <= 15:
                step_mult, event = 0.60, "steps_down_40pct"
            else:
                step_mult, event = 0.40, "steps_down_60pct"
        this_hr = hr + deltas["resting_hr_bpm"] * sev
        this_hrv = hrv + deltas["hrv_rmssd_ms"] * sev
        rows.append(_day(d, sev, w, steps * step_mult * _weekday_step_factor(d), this_hr, this_hrv, sleep, event=event))
    return rows


# ---------------------------------------------------------------------------------------------
# P06 -- Cardiac stress. cardiac_stress scenario; severity_target ramps 0.20->0.40 over days
# 4-21; discrete exertion episodes on days 6, 10, 14, 18 (extra HR/step/HRV spike that day only).
# ---------------------------------------------------------------------------------------------
def schedule_p06(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    deltas = DELTAS_AT_SEVERITY_1["cardiac_stress"]
    exertion_days = {6, 10, 14, 18}
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        sev = 0.20 if d < 4 else 0.20 + (0.40 - 0.20) * (d - 4) / (21 - 4)
        this_hr = hr + deltas["resting_hr_bpm"] * sev
        this_hrv = hrv + deltas["hrv_rmssd_ms"] * sev
        # Continuous chronic step reduction scaling with severity (same additive convention as
        # HR/HRV above and as generate_wearable_trends.py's own baseline+delta*severity formula) --
        # on top of ordinary weekday/weekend variation.
        this_steps = (steps + deltas["steps_per_day"] * sev) * _weekday_step_factor(d)
        event = "cardiac_stress_ramp" if d >= 4 else None
        if d in exertion_days:
            # discrete exertion spike: HR up further, steps/HRV briefly down more, that day only
            this_hr += 15.0
            this_hrv -= 8.0
            this_steps *= 0.6
            event = "exertion_episode"
        rows.append(_day(d, sev, w, this_steps, this_hr, this_hrv, sleep, event=event))
    return rows


# ---------------------------------------------------------------------------------------------
# P07 -- Sudden deterioration. Normal days 1-9; days 10-13 severity_target jumps 0.20->0.40
# (acute_deterioration), then held at 0.40 through day 21; steps drop sharply from day 10.
# ---------------------------------------------------------------------------------------------
def schedule_p07(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    deltas = DELTAS_AT_SEVERITY_1["acute_deterioration"]
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        if d < 10:
            sev, event = 0.20, None
        elif d <= 13:
            sev = 0.20 + (0.40 - 0.20) * (d - 9) / (13 - 9)  # jump over days 10-13
            event = "acute_jump"
        else:
            sev, event = 0.40, "acute_held"
        this_hr = hr + deltas["resting_hr_bpm"] * sev
        this_hrv = hrv + deltas["hrv_rmssd_ms"] * sev
        step_mult = 1.0 if d < 10 else 0.5  # sharp drop from day 10
        rows.append(_day(d, sev, w, steps * step_mult * _weekday_step_factor(d), this_hr, this_hrv, sleep, event=event))
    return rows


# ---------------------------------------------------------------------------------------------
# P08 -- Stressful fortnight, healthy heart. Acute stress days 5, 9, 12, 16 (brief HR/HRV spike,
# wearable only); poor sleep days 8-14 (HR +5-8bpm, HRV -20%, wearable only); back to normal days
# 15-21; severity_target 0.20 throughout (flat -- healthy heart, no real deterioration).
# ---------------------------------------------------------------------------------------------
def schedule_p08(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    stress_days = {5, 9, 12, 16}
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        this_hr, this_hrv, this_sleep = hr, hrv, sleep
        event, sleep_only = None, False
        if 8 <= d <= 14:
            this_hr += 6.5
            this_hrv -= this_hrv * 0.20
            this_sleep -= 1.2
            event, sleep_only = "poor_sleep_fortnight", True
        if d in stress_days:
            this_hr += 10.0
            this_hrv -= 5.0
            event = "acute_stress_episode"
            sleep_only = False  # the stress spike itself is a separate (not sleep) event this day
        rows.append(_day(d, 0.20, w, steps * _weekday_step_factor(d), this_hr, this_hrv, this_sleep,
                          event=event, sleep_input_only=sleep_only))
    return rows


# ---------------------------------------------------------------------------------------------
# P09 -- Active, stable patient. Light Exercise on alternate days from day 4; steps higher than
# baseline; severity_target 0.20 throughout.
# ---------------------------------------------------------------------------------------------
def schedule_p09(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        this_steps = steps * _weekday_step_factor(d) * 1.25  # consistently more active baseline
        event = None
        if d >= 4 and (d - 4) % 2 == 0:
            this_steps *= 1.3  # light exercise day, extra steps on top
            event = "light_exercise"
        rows.append(_day(d, 0.20, w, this_steps, hr - 2.0, hrv + 4.0, sleep, event=event))
    return rows


# ---------------------------------------------------------------------------------------------
# P10 -- Everything goes wrong. From day 4: weight +0.4kg/day, steps -50%, stress days 6 and 10,
# poor sleep days 8-14; severity_target 0.20->0.45 over days 4-21.
# ---------------------------------------------------------------------------------------------
def schedule_p10(base):
    hr, steps, hrv, sleep, w = base["resting_hr_bpm"], base["steps_per_day"], base["hrv_rmssd_ms"], base["sleep_hours"], base["weight_kg"]
    deltas = DELTAS_AT_SEVERITY_1["acute_deterioration"]
    stress_days = {6, 10}
    rows = []
    for d in range(1, MONITORED_DAYS + 1):
        sev = 0.20 if d < 4 else 0.20 + (0.45 - 0.20) * (d - 4) / (21 - 4)
        weight = w + (0.4 * max(d - 3, 0))
        this_hr = hr + deltas["resting_hr_bpm"] * sev
        this_hrv = hrv + deltas["hrv_rmssd_ms"] * sev
        this_sleep = sleep
        step_mult = 1.0 if d < 4 else 0.50
        event, sleep_only = ("everything_ramp" if d >= 4 else None), False
        if 8 <= d <= 14:
            this_hr += 6.0
            this_hrv -= this_hrv * 0.15
            this_sleep -= 1.0
            event, sleep_only = "poor_sleep", True
        if d in stress_days:
            this_hr += 12.0
            this_hrv -= 6.0
            event, sleep_only = "acute_stress_episode", False
        rows.append(_day(d, sev, weight, steps * step_mult * _weekday_step_factor(d), this_hr, this_hrv, this_sleep,
                          event=event, sleep_input_only=sleep_only))
    return rows


PATIENTS = {
    "P01": dict(
        story="Stable patient, ordinary life", expected_group="should_stay_quiet",
        age=58, sex="Female", height_cm=162.0, weight_kg=70.0,
        baseline_ef_pct=64.0, baseline_bnp_pg_ml=90.0,
        baseline=dict(resting_hr_bpm=68.0, steps_per_day=6200.0, hrv_rmssd_ms=36.0, sleep_hours=7.1, spo2_pct=97.5, weight_kg=70.0),
        schedule_fn=schedule_p01,
    ),
    "P02": dict(
        story="Salty weekend", expected_group="edge_case",
        age=50, sex="Male", height_cm=178.0, weight_kg=88.0,
        baseline_ef_pct=60.0, baseline_bnp_pg_ml=110.0,
        baseline=dict(resting_hr_bpm=72.0, steps_per_day=6800.0, hrv_rmssd_ms=34.0, sleep_hours=7.0, spo2_pct=97.0, weight_kg=88.0),
        schedule_fn=schedule_p02,
    ),
    "P03": dict(
        story="Slow, quiet weight gain", expected_group="edge_case",
        age=75, sex="Female", height_cm=158.0, weight_kg=68.0,
        baseline_ef_pct=58.0, baseline_bnp_pg_ml=180.0,
        baseline=dict(resting_hr_bpm=74.0, steps_per_day=5200.0, hrv_rmssd_ms=30.0, sleep_hours=6.8, spo2_pct=96.0, weight_kg=68.0),
        schedule_fn=schedule_p03,
    ),
    "P04": dict(
        story="Fluid overload building up", expected_group="should_catch",
        age=70, sex="Male", height_cm=170.0, weight_kg=95.0,
        baseline_ef_pct=30.0, baseline_bnp_pg_ml=650.0,
        baseline=dict(resting_hr_bpm=78.0, steps_per_day=5500.0, hrv_rmssd_ms=28.0, sleep_hours=6.9, spo2_pct=94.5, weight_kg=95.0),
        schedule_fn=schedule_p04,
    ),
    "P05": dict(
        story="Gradual deconditioning", expected_group="should_catch",
        age=82, sex="Female", height_cm=155.0, weight_kg=60.0,
        baseline_ef_pct=55.0, baseline_bnp_pg_ml=320.0,
        baseline=dict(resting_hr_bpm=70.0, steps_per_day=4200.0, hrv_rmssd_ms=26.0, sleep_hours=7.0, spo2_pct=95.5, weight_kg=60.0),
        schedule_fn=schedule_p05,
    ),
    "P06": dict(
        story="Cardiac stress", expected_group="should_catch",
        age=60, sex="Male", height_cm=180.0, weight_kg=100.0,
        baseline_ef_pct=58.0, baseline_bnp_pg_ml=280.0,
        baseline=dict(resting_hr_bpm=75.0, steps_per_day=6600.0, hrv_rmssd_ms=32.0, sleep_hours=7.0, spo2_pct=96.0, weight_kg=100.0),
        schedule_fn=schedule_p06,
    ),
    "P07": dict(
        story="Sudden deterioration", expected_group="should_catch",
        age=68, sex="Female", height_cm=165.0, weight_kg=80.0,
        baseline_ef_pct=28.0, baseline_bnp_pg_ml=700.0,
        baseline=dict(resting_hr_bpm=80.0, steps_per_day=5800.0, hrv_rmssd_ms=27.0, sleep_hours=7.0, spo2_pct=94.0, weight_kg=80.0),
        schedule_fn=schedule_p07,
    ),
    "P08": dict(
        story="Stressful fortnight, healthy heart", expected_group="should_stay_quiet",
        age=45, sex="Male", height_cm=175.0, weight_kg=82.0,
        baseline_ef_pct=65.0, baseline_bnp_pg_ml=80.0,
        baseline=dict(resting_hr_bpm=65.0, steps_per_day=7200.0, hrv_rmssd_ms=42.0, sleep_hours=7.3, spo2_pct=97.5, weight_kg=82.0),
        schedule_fn=schedule_p08,
    ),
    "P09": dict(
        story="Active, stable patient", expected_group="should_stay_quiet",
        age=52, sex="Female", height_cm=168.0, weight_kg=65.0,
        baseline_ef_pct=66.0, baseline_bnp_pg_ml=70.0,
        baseline=dict(resting_hr_bpm=60.0, steps_per_day=8500.0, hrv_rmssd_ms=45.0, sleep_hours=7.5, spo2_pct=98.0, weight_kg=65.0),
        schedule_fn=schedule_p09,
    ),
    "P10": dict(
        story="Everything goes wrong", expected_group="should_catch",
        age=73, sex="Male", height_cm=172.0, weight_kg=92.0,
        baseline_ef_pct=25.0, baseline_bnp_pg_ml=900.0,
        baseline=dict(resting_hr_bpm=82.0, steps_per_day=5400.0, hrv_rmssd_ms=24.0, sleep_hours=6.7, spo2_pct=93.5, weight_kg=92.0),
        schedule_fn=schedule_p10,
    ),
}


def build():
    cohort = {
        "meta": {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "results_tag": "results-rc1",
            "note": "Provisional, unreviewed: pending PR #4 merge (see docs/integration_pre_results.md).",
            "seeds": SEEDS,
            "baseline_days": BASELINE_DAYS,
            "monitored_days": MONITORED_DAYS,
            "seed_affects": "synthetic wearable noise only -- this file's own schedule is deterministic and seed-independent",
            "demographic_ranges_used": {
                "age": "generator mean=68.72 sd=13.73 range=[18,95] (reference_stats.yaml); this cohort spans 45-82",
                "sex": "generator male_ratio=0.563; this cohort uses 5 male / 5 female",
                "height_cm": "generator male mean=174.32 sd=7.77, female mean=160.46 sd=7.13",
                "weight_kg": "generator male mean=86.43 sd=21.3, female mean=75.99 sd=21.78",
                "ejection_fraction_pct": "generator profiles: healthy mean=62 range=[55,70], hfpef mean=56.9 range=[50,80], hfref mean=32.3 range=[14,40]",
            },
        },
        "patients": {},
    }
    for pid, cfg in PATIENTS.items():
        schedule = cfg["schedule_fn"](cfg["baseline"])
        cohort["patients"][pid] = {
            "story": cfg["story"],
            "expected_group": cfg["expected_group"],
            "demographics": {
                "age": cfg["age"], "sex": cfg["sex"],
                "height_cm": cfg["height_cm"], "weight_kg": cfg["weight_kg"],
            },
            "baseline_clinical_report": {
                "ejection_fraction_pct": cfg["baseline_ef_pct"],
                "nt_probnp_pg_ml": cfg["baseline_bnp_pg_ml"],
            },
            "baseline_wearable": cfg["baseline"],
            "monitored_day_schedule": schedule,
        }
    return cohort


def main():
    cohort = build()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w") as f:
        yaml.dump(cohort, f, default_flow_style=False, sort_keys=False, width=100)
    print(f"Wrote {OUTPUT_PATH} -- {len(cohort['patients'])} patients x {MONITORED_DAYS} monitored days")


if __name__ == "__main__":
    main()
