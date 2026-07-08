"""Validation tests for the Phase 4 batch sampling logic (src/pulse_runner/batch_runner.py).

Only sample_patients() is tested here -- pure pandas, no Docker/Pulse required. _run_one()/
run_batch() actually invoke Pulse and can only be exercised inside the Docker container (see
scripts/validate_phase2.py's equivalent manual-validation convention for Phase 2).

Run from repo root: pytest tests/test_batch_runner.py -v
"""
import pandas as pd
import pytest

from src.data_synthesis.generate_patients import generate_patients
from src.pulse_runner.batch_runner import sample_patients

SCENARIO_TYPES = ["stable", "fluid_overload", "cardiac_stress", "deconditioning", "acute_deterioration"]


@pytest.fixture(scope="module")
def patients() -> pd.DataFrame:
    # n=500 with the default seed gives ~100 patients per scenario type -- comfortably more than
    # any n_per_scenario used in these tests.
    return generate_patients(n=500, seed=7)


class TestSamplePatients:
    def test_correct_count_per_scenario(self, patients):
        sample = sample_patients(patients, n_per_scenario=10, seed=1)
        counts = sample["scenario_type"].value_counts()
        for scenario_type in SCENARIO_TYPES:
            assert counts[scenario_type] == 10

    def test_no_duplicate_patients(self, patients):
        sample = sample_patients(patients, n_per_scenario=10, seed=1)
        assert sample["patient_id"].is_unique

    def test_deterministic_given_seed(self, patients):
        a = sample_patients(patients, n_per_scenario=10, seed=5)
        b = sample_patients(patients, n_per_scenario=10, seed=5)
        pd.testing.assert_frame_equal(
            a.sort_values("patient_id").reset_index(drop=True),
            b.sort_values("patient_id").reset_index(drop=True),
        )

    def test_different_seeds_give_different_samples(self, patients):
        a = sample_patients(patients, n_per_scenario=10, seed=1)
        b = sample_patients(patients, n_per_scenario=10, seed=2)
        assert set(a["patient_id"]) != set(b["patient_id"])

    def test_sampled_rows_are_real_patient_rows(self, patients):
        sample = sample_patients(patients, n_per_scenario=10, seed=1)
        merged = sample.merge(patients, on="patient_id", suffixes=("", "_orig"))
        assert (merged["severity"] == merged["severity_orig"]).all()
