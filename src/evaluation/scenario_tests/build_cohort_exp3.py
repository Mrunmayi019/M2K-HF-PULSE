"""Builds config/scenario_tests/cohort_exp3.yaml -- the Experiment 3 cohort
(results/scenario_tests/exp3/PREREGISTRATION.md).

Experiment 3 runs the Experiment 2 cohort unchanged (same patients, stories, EF 58-67%, seeds
48-53, one warm-up day), with ENABLE_BASELINE_ANCHOR on and BASELINE_REFRESH_DAYS=7. Only `meta`
differs from cohort_exp2.yaml: experiment number, note, and `required_flags`, which
run_patient_seed.py checks before starting.

Usage:
    PYTHONPATH=. python3 -m src.evaluation.scenario_tests.build_cohort_exp3
"""
from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCE_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort_exp2.yaml"
OUTPUT_PATH = REPO_ROOT / "config" / "scenario_tests" / "cohort_exp3.yaml"

REQUIRED_FLAGS = {
    "PIPELINE_MODE": "fresh",  # the harness calls the continuous pipeline directly either way
    "ENABLE_BCG_MODIFIERS": False,
    "ENABLE_HR_BASELINE": False,
    "ENABLE_ALERT_HYSTERESIS": False,
    "ENABLE_SCENARIO_PERSISTENCE": False,
    "ENABLE_BASELINE_ANCHOR": True,
    "BASELINE_REFRESH_DAYS": 7,
}


def build():
    cohort = yaml.safe_load(SOURCE_PATH.read_text())
    meta = cohort["meta"]
    meta["experiment"] = 3
    meta["note"] = (
        "Experiment 3 (results/scenario_tests/exp3/PREREGISTRATION.md). The Experiment 2 cohort "
        "unchanged, run with ENABLE_BASELINE_ANCHOR=1 and BASELINE_REFRESH_DAYS=7."
    )
    meta["source_cohort"] = "config/scenario_tests/cohort_exp2.yaml"
    meta["required_flags"] = REQUIRED_FLAGS
    return cohort


def main():
    OUTPUT_PATH.write_text(yaml.safe_dump(build(), sort_keys=False))
    print("wrote", OUTPUT_PATH)


if __name__ == "__main__":
    main()
