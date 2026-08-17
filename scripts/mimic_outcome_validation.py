"""HANDOFF.md P1 "real clinical outcome validation" -- narrow-scope pass (Step 3/4).

Tests ONE mechanism -- src/analytics/risk_score.py's baseline_deficit_score term, a pure function
of map_start (how congested a patient's baseline mean arterial pressure already is) -- against
real in-hospital mortality in a real MIMIC-IV heart-failure cohort.

**Scope, stated plainly (see docs/methodology.md's new subsection for the full writeup)**: this
validates the chronic-baseline-congestion mechanism only. It does NOT validate, and this script
does NOT touch: the wearable-trend ML scenario classifier (Model 1), the Pulse simulation layer,
or risk_score.py's acute-change components (hr_rise/map_drop/co_drop_pct/compensation_flag/
instability_flag) -- none of those have a valid, non-fabricated input in MIMIC-IV (see the
planning discussion this was scoped from: EF has 0 real measurements in this dataset; median
hospital stay is 3 days, so no honest 21-day wearable-trend window exists at all).

Isolation trick: compute_risk_score() is called with every ACUTE input fixed at its neutral value
(hr_rise=0, map_drop=0, co_drop_pct=0, compensation_flag=1 [not-failed], instability_flag=0) --
this makes acute_score exactly 0 for every row (verified: NEWS2 HR band for hr_end=70 is 0 pts,
map_drop/co_drop_pct components are 0 at 0 input, compensation_flag=1 -> its component is 0), so
risk_score = max(0, baseline_deficit_score) = baseline_deficit_score exactly. This reuses the
existing, tested public function unmodified rather than reaching into a private helper.

Cohort: see scripts/mimic_outcome_extraction.sql for the full extraction query and its inclusion
criteria. In short -- HF admissions (ICD-9 428.x / ICD-10 I50.x) with >=1 real MAP reading
strictly within the first 24h of admission (the map_start guardrail); NT-proBNP and
discharge_location are deliberately not used at all (diagnostic-not-predictive / outcome-adjacent,
per the explicit scope decision this was built from); not filtered by outcome.

Usage: python -m scripts.mimic_outcome_validation
Reads:  data/raw/mimic/hf_admission_outcomes.csv (gitignored -- real patient-level MIMIC-IV data,
        produced by scripts/mimic_outcome_extraction.sql)
Writes: data/mimic_outcome_validation/results.csv, data/mimic_outcome_validation/summary.md
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from src.analytics.risk_score import compute_risk_score

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
INPUT_CSV = REPO_ROOT / "data" / "raw" / "mimic" / "hf_admission_outcomes.csv"
OUT_DIR = REPO_ROOT / "data" / "mimic_outcome_validation"

N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42
N_CALIBRATION_BINS = 10


def bootstrap_auc_ci(y_true: np.ndarray, y_score: np.ndarray, n_resamples: int = N_BOOTSTRAP, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """Percentile-bootstrap 95% CI for AUC, resampling (score, outcome) pairs together. Same
    pattern as scripts/model1_extended_eval.py's bootstrap_ci -- kept local here since this
    script's resampling unit (paired rows, not a single 1-D array) differs slightly."""
    rng = np.random.default_rng(seed)
    n = len(y_true)
    point = roc_auc_score(y_true, y_score)
    boot_aucs = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        yt, ys = y_true[idx], y_score[idx]
        # A resample with only one outcome class can't produce an AUC -- skip and retry.
        while yt.min() == yt.max():
            idx = rng.integers(0, n, size=n)
            yt, ys = y_true[idx], y_score[idx]
        boot_aucs[i] = roc_auc_score(yt, ys)
    lo, hi = np.percentile(boot_aucs, [2.5, 97.5])
    return point, lo, hi


def compute_baseline_deficit_only(map_start: float) -> float:
    result = compute_risk_score(
        hr_rise=0, map_drop=0, co_drop_pct=0, compensation_flag=1, instability_flag=0,
        map_start=map_start,
    )
    assert result["acute_score"] == 0.0, "neutral acute inputs must yield acute_score == 0"
    return result["risk_score"]


def main() -> None:
    if not INPUT_CSV.exists():
        raise FileNotFoundError(
            f"{INPUT_CSV} not found. Run scripts/mimic_outcome_extraction.sql via bq first "
            "(see that file's own header for the exact command)."
        )
    df = pd.read_csv(INPUT_CSV)
    n_total = len(df)
    n_patients = df["subject_id"].nunique()

    df["baseline_deficit_score"] = df["map_start_mmhg"].apply(compute_baseline_deficit_only)

    y_true = df["hospital_expire_flag"].to_numpy()
    y_score = df["baseline_deficit_score"].to_numpy()
    event_rate = y_true.mean()

    auc_point, auc_lo, auc_hi = bootstrap_auc_ci(y_true, y_score)

    # Calibration: decile bins of baseline_deficit_score vs. observed mortality rate per bin.
    df["score_decile"] = pd.qcut(df["baseline_deficit_score"], q=N_CALIBRATION_BINS, duplicates="drop")
    calibration = (
        df.groupby("score_decile", observed=True)
        .agg(n=("hospital_expire_flag", "size"),
             mean_score=("baseline_deficit_score", "mean"),
             observed_mortality_rate=("hospital_expire_flag", "mean"))
        .reset_index(drop=True)
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_DIR / "results.csv", index=False)

    lines = [
        "# MIMIC-IV real-outcome test: baseline_deficit_score mechanism only",
        "",
        "**Scope**: this tests ONE mechanism in `src/analytics/risk_score.py` --"
        " `baseline_deficit_score = f(map_start)` -- against real in-hospital mortality. It does"
        " NOT validate the full risk scorer, the wearable-trend ML classifier, or the Pulse"
        " simulation layer; none of those have a non-fabricated input in MIMIC-IV. See"
        " `scripts/mimic_outcome_extraction.sql` for the exact cohort query and"
        " `docs/methodology.md` for the full writeup.",
        "",
        "## Cohort",
        "",
        f"- n = {n_total} admissions ({n_patients} unique patients) -- **exact count, no"
        f" extrapolation.**",
        f"- In-hospital mortality (event) rate: {event_rate:.1%} ({int(y_true.sum())} deaths)",
        f"- map_start: mean of real MAP readings strictly within the first 24h of admission"
        f" (mean {df['map_start_mmhg'].mean():.1f} mmHg, sd {df['map_start_mmhg'].std():.1f},"
        f" median {df['n_map_readings_24h'].median():.0f} readings/admission)",
        f"- Age: mean {df['age'].mean():.1f} (sd {df['age'].std():.1f}); "
        f"sex: {(df['sex'] == 'M').mean():.1%} male",
        "",
        "## Discrimination (AUC)",
        "",
        f"- AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f}, percentile bootstrap,"
        f" {N_BOOTSTRAP} resamples, seed={BOOTSTRAP_SEED}) for baseline_deficit_score predicting"
        f" hospital_expire_flag.",
        "- AUC 0.5 = no better than chance; 1.0 = perfect discrimination. This is ONE hand-tuned"
        " component's discrimination, evaluated in isolation -- not the full risk_score.py output"
        " (which also weighs acute hemodynamic change from a Pulse-simulated encounter that has"
        " no equivalent here).",
        "",
        "## Calibration (decile bins)",
        "",
        "```",
        calibration.round(4).to_string(index=False),
        "```",
        "",
        "## Honest limitations of this specific test",
        "",
        "- **Population mismatch**: this cohort is ICU-admitted MIMIC-IV patients (vitalsign, the"
        " MAP source, is an ICU-derived table) -- an acutely ill, already-hospitalized population,"
        " not this project's target outpatient/home-monitoring use case. A baseline MAP measured"
        " during an ICU stay reflects that acute presentation, not a stable ambulatory baseline.",
        "- **map_start's real-world meaning differs from its synthetic/Pulse-simulated use"
        " elsewhere in this project**: in the synthetic pipeline, map_start is a Pulse-simulated"
        " patient's baseline before a scenario encounter; here it's a real, directly measured"
        " first-24h ICU MAP. Same formula, different data-generating process.",
        "- **Admission-level, not patient-level, sampling**: a subject_id can contribute more than"
        " one admission (13,047 unique patients across 17,129 admissions here), which mildly"
        " violates the independence assumption behind the AUC CI -- not corrected for in this"
        " pass.",
        "- **NT-proBNP and discharge_location were deliberately excluded** from this test (see"
        " module docstring) -- this is a narrower test than 'everything MIMIC could offer', by"
        " design.",
        "- **hospital_expire_flag is in-hospital mortality only** -- no post-discharge (dod-based)"
        " or readmission outcome was pursued in this pass (flagged as future work).",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines))

    print("\n".join(lines))
    print(f"\nWrote {OUT_DIR / 'results.csv'} and {OUT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
