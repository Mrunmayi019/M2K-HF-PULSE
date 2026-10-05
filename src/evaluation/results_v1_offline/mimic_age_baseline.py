"""results-v1 offline analysis (3/4, completed 2026-10-06): age-only baseline AUC, compared
against the existing baseline_deficit_score AUC (data/mimic_outcome_validation/summary.md), on
the SAME MIMIC-IV cohort (data/raw/mimic/hf_admission_outcomes.csv -- gitignored, row-level real
patient data, read but never written back; only aggregate numbers below leave this script).

Reuses scripts/mimic_outcome_validation.py's own bootstrap_auc_ci() (copied verbatim, not
reimplemented differently) for an apples-to-apples CI methodology. Does not modify that script.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.results_v1_offline.mimic_age_baseline
"""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
INPUT_CSV = REPO_ROOT / "data" / "raw" / "mimic" / "hf_admission_outcomes.csv"
OUT_DIR = REPO_ROOT / "results" / "results_v1_offline"

N_BOOTSTRAP = 2000
BOOTSTRAP_SEED = 42


def bootstrap_auc_ci(y_true: np.ndarray, y_score: np.ndarray, n_resamples: int = N_BOOTSTRAP,
                      seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """Verbatim copy of scripts/mimic_outcome_validation.py::bootstrap_auc_ci() -- same
    percentile-bootstrap methodology, so the age-baseline CI is directly comparable to the
    existing baseline_deficit_score CI."""
    rng = np.random.default_rng(seed)
    n = len(y_true)
    point = roc_auc_score(y_true, y_score)
    boot_aucs = np.empty(n_resamples)
    for i in range(n_resamples):
        idx = rng.integers(0, n, size=n)
        yt, ys = y_true[idx], y_score[idx]
        while yt.min() == yt.max():
            idx = rng.integers(0, n, size=n)
            yt, ys = y_true[idx], y_score[idx]
        boot_aucs[i] = roc_auc_score(yt, ys)
    lo, hi = np.percentile(boot_aucs, [2.5, 97.5])
    return point, lo, hi


def main():
    if not INPUT_CSV.exists():
        raise SystemExit(f"{INPUT_CSV} not found -- stopping, not selecting a GCP project.")

    df = pd.read_csv(INPUT_CSV)
    y_true = df["hospital_expire_flag"].to_numpy()
    age_auc, age_lo, age_hi = bootstrap_auc_ci(y_true, df["age"].to_numpy())

    summary = {
        "n_admissions": len(df),
        "n_patients": int(df["subject_id"].nunique()),
        "mortality_rate": round(float(y_true.mean()), 4),
        "age_baseline_auc": round(age_auc, 4),
        "age_baseline_auc_ci95": [round(age_lo, 4), round(age_hi, 4)],
        "existing_baseline_deficit_score_auc": 0.596,
        "existing_baseline_deficit_score_auc_ci95": [0.585, 0.608],
    }
    print(json.dumps(summary, indent=2))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / "mimic_age_baseline.json", "w") as f:
        json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
