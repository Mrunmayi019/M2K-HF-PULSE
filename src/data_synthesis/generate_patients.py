"""Correlated synthetic patient generator.

Generates a population of synthetic (never real) patients, each assigned one of the 5 locked
scenario types (see docs/architecture.md), with ejection fraction, NT-proBNP, and NYHA class
derived *conditionally* on each other and on assigned severity rather than sampled independently,
so the resulting dataset reflects real clinical correlation (low EF -> high BNP -> high NYHA class).

Every constant below traces to a row in docs/data_provenance.md via reference_stats.yaml.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pandas as pd
import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
REFERENCE_STATS_PATH = pathlib.Path(__file__).resolve().parent / "reference_stats.yaml"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "synthetic" / "patients.csv"

# Which EF baseline profile (from reference_stats.yaml -> ejection_fraction) each scenario type
# is centered on before severity pulls it down. Deconditioning and cardiac_stress patients are
# modeled as HFpEF-like (preserved EF, symptomatic on exertion) rather than HFrEF.
SCENARIO_EF_PROFILE = {
    "stable": "healthy",
    "deconditioning": "hfpef",
    "cardiac_stress": "hfpef",
    "fluid_overload": "hfref",
    "acute_deterioration": "hfref",
}

NYHA_CLASSES = ["I", "II", "III", "IV"]


def load_reference_stats(path: pathlib.Path = REFERENCE_STATS_PATH) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _sample_demographics(rng: np.random.Generator, stats: dict, n: int) -> pd.DataFrame:
    age_cfg = stats["age"]
    age = np.clip(rng.normal(age_cfg["mean"], age_cfg["sd"], n), age_cfg["min"], age_cfg["max"])

    sex_ratio = stats["sex_ratio"]
    sex = rng.choice(["Male", "Female"], size=n, p=[sex_ratio["male"], sex_ratio["female"]])

    height_cfg = stats["height_cm"]
    weight_cfg = stats["weight_kg"]
    height = np.where(
        sex == "Male",
        rng.normal(height_cfg["male"]["mean"], height_cfg["male"]["sd"], n),
        rng.normal(height_cfg["female"]["mean"], height_cfg["female"]["sd"], n),
    )
    weight = np.where(
        sex == "Male",
        rng.normal(weight_cfg["male"]["mean"], weight_cfg["male"]["sd"], n),
        rng.normal(weight_cfg["female"]["mean"], weight_cfg["female"]["sd"], n),
    )
    height = np.clip(height, 140, 210)
    weight = np.clip(weight, 40, 180)
    bmi = weight / (height / 100) ** 2

    return pd.DataFrame(
        {
            "age": np.round(age, 1),
            "sex": sex,
            "height_cm": np.round(height, 1),
            "weight_kg": np.round(weight, 1),
            "bmi": np.round(bmi, 1),
        }
    )


def _assign_scenario(rng: np.random.Generator, stats: dict, n: int) -> pd.DataFrame:
    scenario_type = rng.choice(stats["scenario_types"], size=n)
    severity = rng.uniform(0, 1, n)
    # "stable" is stable by definition -- cap its severity low regardless of the uniform draw.
    severity = np.where(scenario_type == "stable", severity * 0.15, severity)
    return pd.DataFrame({"scenario_type": scenario_type, "severity": np.round(severity, 3)})


def _bnp_cutoff_for_age(age: np.ndarray, stats: dict) -> np.ndarray:
    cutoffs = stats["nt_probnp_cutoff_pg_ml"]
    return np.select(
        [age < 50, age <= 75],
        [cutoffs["under_50"], cutoffs["50_to_75"]],
        default=cutoffs["over_75"],
    )


def _derive_clinical_state(
    rng: np.random.Generator, stats: dict, scenario_type: np.ndarray, severity: np.ndarray, age: np.ndarray
) -> pd.DataFrame:
    ef_profiles = stats["ejection_fraction"]
    profile_key = np.vectorize(SCENARIO_EF_PROFILE.get)(scenario_type)

    ef_center = np.vectorize(lambda k: ef_profiles[k]["mean"])(profile_key)
    ef_spread = np.vectorize(lambda k: (ef_profiles[k]["range"][1] - ef_profiles[k]["range"][0]) / 4)(profile_key)

    # Higher severity pulls EF down within its scenario's profile, not across profiles --
    # a "stable" patient never becomes HFrEF just from a severity roll.
    ef = rng.normal(ef_center, ef_spread) - severity * 12
    ef = np.clip(ef, 15, 75)

    # bnp_score in [0, 1]: composite of how depressed EF is + how severe the scenario roll was.
    # This is what makes BNP negatively correlated with EF and positively with severity by
    # construction, which tests/test_data_synthesis.py checks for.
    ef_deficit = np.clip((70 - ef) / 55, 0, 1)
    bnp_score = np.clip(0.6 * ef_deficit + 0.4 * severity, 0, 1)

    cutoff = _bnp_cutoff_for_age(age, stats)
    # BNP is clinically right-skewed -- lognormal noise keeps the tail realistic instead of
    # letting a symmetric normal produce implausible negative values.
    noise = rng.lognormal(mean=0, sigma=0.25, size=len(ef))
    nt_probnp = cutoff * (0.25 + 2.0 * bnp_score) * noise

    composite = np.clip(0.5 * bnp_score + 0.5 * severity + rng.normal(0, 0.05, len(ef)), 0, 1)
    nyha_idx = np.select(
        [composite < 0.15, composite < 0.4, composite < 0.7],
        [0, 1, 2],
        default=3,
    )
    nyha_class = np.array(NYHA_CLASSES)[nyha_idx]

    return pd.DataFrame(
        {
            "ejection_fraction_pct": np.round(ef, 1),
            "nt_probnp_pg_ml": np.round(nt_probnp, 1),
            "nyha_class": nyha_class,
        }
    )


def generate_patients(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Generate `n` correlated synthetic patients. Deterministic given `seed`."""
    rng = np.random.default_rng(seed)
    stats = load_reference_stats()

    demographics = _sample_demographics(rng, stats, n)
    scenario = _assign_scenario(rng, stats, n)
    clinical = _derive_clinical_state(
        rng, stats, scenario["scenario_type"].to_numpy(), scenario["severity"].to_numpy(), demographics["age"].to_numpy()
    )

    df = pd.concat([demographics, scenario, clinical], axis=1)
    df.insert(0, "patient_id", [f"P{i:04d}" for i in range(n)])
    return df


if __name__ == "__main__":
    # n=2000 (not the function default of 500): Phase 3's 70/15/15 patient-level split needs
    # enough per-scenario samples in the 15% test fold for 5-class evaluation to mean anything.
    patients = generate_patients(n=2000)
    DEFAULT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    patients.to_csv(DEFAULT_OUTPUT_PATH, index=False)
    print(f"Wrote {len(patients)} patients to {DEFAULT_OUTPUT_PATH}")
    print(patients.describe(include="all"))
