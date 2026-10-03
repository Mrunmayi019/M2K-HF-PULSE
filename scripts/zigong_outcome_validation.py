"""Second real-outcome test of the SAME single mechanism as scripts/mimic_outcome_validation.py --
src/analytics/risk_score.py's baseline_deficit_score term, a pure function of map_start -- this
time against the Zigong heart-failure cohort (PhysioNet, DUA-signed, restricted access):
"Hospitalized patients with heart failure: integrating electronic healthcare records and external
outcome data" v1.3.

**Scope, stated plainly (see docs/methodology.md's new subsection for the full writeup)**: this
validates the chronic-baseline-congestion mechanism only, against a broader composite outcome
(death-or-readmission within 6 months) in a second, independent real cohort. It does NOT validate
the wearable-trend ML scenario classifier (Model 1), the Pulse simulation layer, or risk_score.py's
acute-change components -- none of those have a non-fabricated input here either: this dataset is a
single per-admission snapshot (no 21-day ambulatory wearable window, no Pulse-simulated encounter).

LVEF/NYHA/BNP are NOT fed into this test, despite being present in the dataset: there is no
existing function in this codebase that maps (LVEF, NYHA, BNP) -> risk_score or severity.
risk_score.py's 5 acute-change features are all Pulse-simulation outputs; staging.py's
classify_nyha() runs the opposite direction (EF/BNP + an already-computed risk_score ->  NYHA, not
the reverse); Model 1 needs a 21-day wearable-trend window this dataset cannot supply. Building a
new LVEF/NYHA/BNP proxy was explicitly declined for this pass (repo owner's call) -- see
docs/methodology.md. LVEF/NYHA/BNP are reported descriptively only (cohort stats), consistent with
the reconnaissance already done.

Isolation trick (identical to scripts/mimic_outcome_validation.py): compute_risk_score() is called
with every acute input fixed at its neutral value (hr_rise=0, map_drop=0, co_drop_pct=0,
compensation_flag=1 [not-failed], instability_flag=0) so acute_score == 0 for every row and
risk_score = max(0, baseline_deficit_score) = baseline_deficit_score exactly. Reuses the existing,
tested public function unmodified.

Usage: python -m scripts.zigong_outcome_validation
Reads:  the dataset directory (see DATA_DIR below) -- dat.csv, dataDictionary.csv. Outside the repo
        (DUA-signed restricted-access data, never committed).
Writes: data/zigong_outcome_validation/results.csv, data/zigong_outcome_validation/summary.md
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, roc_auc_score

from src.analytics.risk_score import compute_risk_score

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DATA_DIR = pathlib.Path(
    r"D:\5th sem notes\capstone\Dataset\hospitalized-patients-with-heart-failure-integrating-"
    r"electronic-healthcare-records-and-external-outcome-data-1.3"
)
OUT_DIR = REPO_ROOT / "data" / "zigong_outcome_validation"

N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42
N_CALIBRATION_BINS = 10

# Physiologically-implausible-value cleaning rules, agreed before computing anything.
BMI_CEILING = 60.0  # generous upper bound for even extreme obesity; dataset max was 404 (clear error)
HEIGHT_FLOOR_M = 1.0  # dataset min was 0.35m -- impossible for an adult


def compute_baseline_deficit_only(map_start: float) -> float:
    result = compute_risk_score(
        hr_rise=0, map_drop=0, co_drop_pct=0, compensation_flag=1, instability_flag=0,
        map_start=map_start,
    )
    assert result["acute_score"] == 0.0, "neutral acute inputs must yield acute_score == 0"
    return result["risk_score"]


def bootstrap_metric_ci(y_true: np.ndarray, y_score: np.ndarray, metric_fn, n_resamples: int = N_BOOTSTRAP, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """Percentile-bootstrap 95% CI, resampling (score, outcome) pairs together -- same pattern as
    scripts/mimic_outcome_validation.py's bootstrap_auc_ci, generalized to any sklearn metric that
    takes (y_true, y_score)."""
    rng = np.random.default_rng(seed)
    n = len(y_true)
    point = metric_fn(y_true, y_score)
    boot_vals = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        yt, ys = y_true[idx], y_score[idx]
        while yt.min() == yt.max():
            idx = rng.integers(0, n, size=n)
            yt, ys = y_true[idx], y_score[idx]
        boot_vals[i] = metric_fn(yt, ys)
    lo, hi = np.percentile(boot_vals, [2.5, 97.5])
    return point, lo, hi


def main() -> None:
    dat = pd.read_csv(DATA_DIR / "dat.csv")
    n_raw = len(dat)

    # --- Step 1: cleaning rules, reported individually and combined ---
    rule_pulse_zero = dat["pulse"] == 0
    rule_resp_zero = dat["respiration"] == 0
    rule_sbp_zero = dat["systolic.blood.pressure"] == 0
    rule_height_low = dat["height"] < HEIGHT_FLOOR_M
    rule_bmi_high = dat["BMI"] > BMI_CEILING

    print("=== Cleaning rules (individual drop counts, against n=%d raw) ===" % n_raw)
    print(f"pulse == 0: {rule_pulse_zero.sum()}")
    print(f"respiration == 0: {rule_resp_zero.sum()}")
    print(f"systolic.blood.pressure == 0: {rule_sbp_zero.sum()}")
    print(f"height < {HEIGHT_FLOOR_M}m: {rule_height_low.sum()}")
    print(f"BMI > {BMI_CEILING}: {rule_bmi_high.sum()}")

    drop_mask = rule_pulse_zero | rule_resp_zero | rule_sbp_zero | rule_height_low | rule_bmi_high
    print(f"Combined (union, any rule triggers exclusion): {drop_mask.sum()} dropped")

    dat_clean = dat[~drop_mask].copy()
    n_clean = len(dat_clean)
    print(f"n after cleaning: {n_clean} (from {n_raw})")

    # --- Step 2: complete-case cohort (LVEF + NYHA + BNP + all outcome flags) from cleaned data ---
    outcome_flag_cols = [
        "death.within.28.days", "re.admission.within.28.days",
        "death.within.3.months", "re.admission.within.3.months",
        "death.within.6.months", "re.admission.within.6.months",
    ]
    core_needed = ["LVEF", "NYHA.cardiac.function.classification", "brain.natriuretic.peptide"] + outcome_flag_cols
    complete_mask = dat_clean[core_needed].notna().all(axis=1)
    cohort = dat_clean[complete_mask].copy()
    n_cohort = len(cohort)
    print(f"\n=== Complete-case cohort (LVEF+NYHA+BNP+all 6 outcome flags, from cleaned data) ===")
    print(f"n = {n_cohort} (pre-cleaning reconnaissance figure was 626, on n=2008 raw)")

    # --- Step 3: composite outcome, death-or-readmission within 6 months ---
    cohort["composite_6mo"] = (
        (cohort["death.within.6.months"] == 1) | (cohort["re.admission.within.6.months"] == 1)
    ).astype(int)
    event_rate = cohort["composite_6mo"].mean()
    print(f"\n=== Composite outcome (death OR readmission, 6mo) ===")
    print(f"event rate: {event_rate:.1%} ({cohort['composite_6mo'].sum()} / {n_cohort})")
    print(f"  death.within.6.months alone: {cohort['death.within.6.months'].mean():.1%}")
    print(f"  re.admission.within.6.months alone: {cohort['re.admission.within.6.months'].mean():.1%}")

    # --- Step 4: map onto the EXISTING baseline_deficit_score mechanism (map_start = real `map`) ---
    cohort["baseline_deficit_score"] = cohort["map"].apply(compute_baseline_deficit_only)

    y_true = cohort["composite_6mo"].to_numpy()
    y_score = cohort["baseline_deficit_score"].to_numpy()

    # --- Step 5: AUC + PR-AUC, bootstrapped CIs ---
    auc_point, auc_lo, auc_hi = bootstrap_metric_ci(y_true, y_score, roc_auc_score)
    pr_auc_point, pr_auc_lo, pr_auc_hi = bootstrap_metric_ci(y_true, y_score, average_precision_score)

    print(f"\n=== Discrimination, complete-case cohort (n={n_cohort}) ===")
    print(f"AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f}, {N_BOOTSTRAP} resamples, seed={BOOTSTRAP_SEED})")
    print(f"PR-AUC = {pr_auc_point:.3f} (95% CI {pr_auc_lo:.3f}-{pr_auc_hi:.3f}); baseline (event rate) = {event_rate:.3f}")

    # --- Bonus: same test on the full cleaned cohort (map is 0% missing; not gated by LVEF/NYHA/BNP) ---
    dat_clean["composite_6mo"] = (
        (dat_clean["death.within.6.months"] == 1) | (dat_clean["re.admission.within.6.months"] == 1)
    ).astype(int)
    dat_clean["baseline_deficit_score"] = dat_clean["map"].apply(compute_baseline_deficit_only)
    yt_full = dat_clean["composite_6mo"].to_numpy()
    ys_full = dat_clean["baseline_deficit_score"].to_numpy()
    auc_full, auc_full_lo, auc_full_hi = bootstrap_metric_ci(yt_full, ys_full, roc_auc_score)
    pr_full, pr_full_lo, pr_full_hi = bootstrap_metric_ci(yt_full, ys_full, average_precision_score)
    event_rate_full = yt_full.mean()
    print(f"\n=== BONUS: same test on the full cleaned cohort (n={len(dat_clean)}, not gated by LVEF/NYHA/BNP) ===")
    print(f"event rate: {event_rate_full:.1%}")
    print(f"AUC = {auc_full:.3f} (95% CI {auc_full_lo:.3f}-{auc_full_hi:.3f})")
    print(f"PR-AUC = {pr_full:.3f} (95% CI {pr_full_lo:.3f}-{pr_full_hi:.3f})")

    # Calibration: decile bins of baseline_deficit_score vs. observed composite-outcome rate.
    cohort["score_decile"] = pd.qcut(cohort["baseline_deficit_score"], q=N_CALIBRATION_BINS, duplicates="drop")
    calibration = (
        cohort.groupby("score_decile", observed=True)
        .agg(n=("composite_6mo", "size"),
             mean_score=("baseline_deficit_score", "mean"),
             observed_event_rate=("composite_6mo", "mean"))
        .reset_index(drop=True)
    )
    print("\n=== Calibration (decile bins, complete-case cohort) ===")
    print(calibration.round(4).to_string(index=False))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    cohort.to_csv(OUT_DIR / "results.csv", index=False)

    lines = [
        "# Zigong heart-failure cohort real-outcome test: baseline_deficit_score mechanism only",
        "",
        "**Scope**: second independent real-world test of the SAME single mechanism as"
        " `scripts/mimic_outcome_validation.py` -- `baseline_deficit_score = f(map_start)` -- this"
        " time against a broader composite outcome (death-or-readmission within 6 months). Does NOT"
        " validate the full risk scorer, the wearable-trend ML classifier, or the Pulse simulation"
        " layer. LVEF/NYHA/BNP are present in this dataset but are NOT fed into this test -- no"
        " existing function in this codebase maps them to risk_score or severity (see"
        " `docs/methodology.md` for the full explanation and the repo owner's explicit decision not"
        " to build one for this pass).",
        "",
        "## Cleaning",
        "",
        f"- n raw = {n_raw}",
        f"- Dropped (union of: pulse==0, respiration==0, systolic.blood.pressure==0, height<{HEIGHT_FLOOR_M}m,"
        f" BMI>{BMI_CEILING}): {drop_mask.sum()}",
        f"- n after cleaning = {n_clean}",
        "",
        "## Cohort",
        "",
        f"- Complete-case cohort (LVEF + NYHA + BNP + all 6 outcome flags present, from cleaned"
        f" data): n = {n_cohort}",
        f"- Composite outcome (death OR readmission within 6 months) event rate: {event_rate:.1%}"
        f" ({int(cohort['composite_6mo'].sum())} / {n_cohort})",
        "",
        "## Discrimination (AUC / PR-AUC)",
        "",
        f"- AUC = {auc_point:.3f} (95% CI {auc_lo:.3f}-{auc_hi:.3f}, percentile bootstrap,"
        f" {N_BOOTSTRAP} resamples, seed={BOOTSTRAP_SEED}) for baseline_deficit_score predicting the"
        f" 6-month composite outcome.",
        f"- PR-AUC = {pr_auc_point:.3f} (95% CI {pr_auc_lo:.3f}-{pr_auc_hi:.3f}); event-rate baseline"
        f" = {event_rate:.3f}.",
        f"- Bonus, full cleaned cohort (n={len(dat_clean)}, not gated by LVEF/NYHA/BNP presence,"
        f" since `map` itself is 0% missing): AUC = {auc_full:.3f} (95% CI {auc_full_lo:.3f}-"
        f"{auc_full_hi:.3f}), PR-AUC = {pr_full:.3f} (95% CI {pr_full_lo:.3f}-{pr_full_hi:.3f}),"
        f" event rate = {event_rate_full:.1%}.",
        "",
        "## Calibration (decile bins, complete-case cohort)",
        "",
        "```",
        calibration.round(4).to_string(index=False),
        "```",
        "",
        "## Honest limitations of this specific test",
        "",
        "- **This validates baseline-risk-predicts-future-outcome only. It does NOT validate"
        " day-by-day trend/early-warning detection** (Model 1's actual production use case) --"
        " that remains untested by any real data.",
        "- **Population**: hospitalized HF admissions in Zigong, China -- an already-hospitalized,"
        " acutely-ill population at baseline capture, not this project's target"
        " outpatient/home-monitoring population (same caveat as the MIMIC-IV test).",
        "- **Composite outcome mixes two different event types** (death, readmission) with very"
        " different rates and mechanisms; not decomposed in this pass.",
        "- **LVEF/NYHA/BNP unused** despite being present -- see Scope above.",
        "- **map here is a single admission-time vital**, not a stable ambulatory baseline (same"
        " map_start-meaning caveat as MIMIC-IV).",
        "- **Complete-case cohort is a non-random subset** (patients who happened to get an echo"
        " and a BNP draw) -- may not represent the full 2008-admission population.",
    ]
    (OUT_DIR / "summary.md").write_text("\n".join(lines))
    print(f"\nWrote {OUT_DIR / 'results.csv'} and {OUT_DIR / 'summary.md'}")


if __name__ == "__main__":
    main()
