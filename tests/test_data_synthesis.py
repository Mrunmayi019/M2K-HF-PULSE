"""Validation tests for the Phase 1 synthetic data pipeline.

Run from repo root: pytest tests/test_data_synthesis.py -v
"""
import numpy as np
import pandas as pd
import pytest

from src.data_synthesis.generate_patients import NYHA_CLASSES, generate_patients
from src.data_synthesis.generate_wearable_trends import generate_wearable_trends

N_PATIENTS = 300
SEED = 7


@pytest.fixture(scope="module")
def patients() -> pd.DataFrame:
    return generate_patients(n=N_PATIENTS, seed=SEED)


@pytest.fixture(scope="module")
def trends(patients: pd.DataFrame) -> pd.DataFrame:
    return generate_wearable_trends(patients, days=21, seed=SEED)


class TestPatientSchema:
    def test_row_count_and_unique_ids(self, patients):
        assert len(patients) == N_PATIENTS
        assert patients["patient_id"].is_unique

    def test_expected_columns_present(self, patients):
        expected = {
            "patient_id", "age", "sex", "height_cm", "weight_kg", "bmi",
            "scenario_type", "severity", "ejection_fraction_pct",
            "nt_probnp_pg_ml", "nyha_class",
        }
        assert expected.issubset(patients.columns)

    def test_value_ranges(self, patients):
        assert patients["age"].between(18, 95).all()
        assert patients["ejection_fraction_pct"].between(15, 75).all()
        assert patients["severity"].between(0, 1).all()
        assert patients["nyha_class"].isin(NYHA_CLASSES).all()
        assert (patients["nt_probnp_pg_ml"] > 0).all()


class TestClinicalCorrelation:
    def test_bnp_negatively_correlated_with_ef(self, patients):
        corr = patients["ejection_fraction_pct"].corr(patients["nt_probnp_pg_ml"])
        assert corr < -0.2, f"expected negative EF/BNP correlation, got {corr}"

    def test_nyha_class_worsens_as_ef_drops(self, patients):
        class_order = {c: i for i, c in enumerate(NYHA_CLASSES)}
        nyha_rank = patients["nyha_class"].map(class_order)
        corr = patients["ejection_fraction_pct"].corr(nyha_rank)
        assert corr < -0.2, f"expected EF and NYHA rank to move oppositely, got {corr}"

    def test_stable_scenario_has_low_severity(self, patients):
        stable = patients[patients["scenario_type"] == "stable"]
        assert stable["severity"].max() <= 0.2

    def test_severity_increases_bnp(self, patients):
        corr = patients["severity"].corr(patients["nt_probnp_pg_ml"])
        assert corr > 0.2, f"expected severity/BNP positive correlation, got {corr}"


class TestWearableTrendSchema:
    def test_expected_columns_present(self, trends):
        expected = {
            "patient_id", "day", "scenario_type", "trend_mode",
            "resting_hr_bpm", "spo2_pct", "weight_kg", "steps_per_day",
            "sleep_hours", "hrv_rmssd_ms",
        }
        assert expected.issubset(trends.columns)

    def test_all_modes_present(self, trends):
        modes = set(trends["trend_mode"].unique())
        assert modes == {"stable", "deteriorating", "recovering"}, modes

    def test_days_per_patient(self, trends):
        counts = trends.groupby("patient_id").size()
        assert (counts == 21).all()

    def test_physiological_bounds(self, trends):
        assert trends["spo2_pct"].le(100).all()
        assert trends["steps_per_day"].ge(0).all()
        assert trends["sleep_hours"].ge(0).all()
        assert trends["hrv_rmssd_ms"].ge(1).all()


class TestWearableTrendShapes:
    def _first_last(self, trends, mode, patient_col="resting_hr_bpm"):
        subset = trends[trends["trend_mode"] == mode]
        patient_id = subset["patient_id"].iloc[0]
        series = subset[subset["patient_id"] == patient_id].sort_values("day")
        return series[patient_col].iloc[0], series[patient_col].iloc[-1], series[patient_col]

    def test_deteriorating_hr_rises(self, trends):
        deteriorating = trends[trends["trend_mode"] == "deteriorating"]
        # average end-of-window HR should exceed average start-of-window HR across all
        # deteriorating patients (per-patient noise means not every single one must rise)
        start = deteriorating[deteriorating["day"] == 0]["resting_hr_bpm"].mean()
        end = deteriorating[deteriorating["day"] == 20]["resting_hr_bpm"].mean()
        assert end > start

    def test_recovering_hr_ends_below_its_peak(self, trends):
        recovering = trends[trends["trend_mode"] == "recovering"]
        peak = recovering[recovering["day"] == 0]["resting_hr_bpm"].mean()
        end = recovering[recovering["day"] == 20]["resting_hr_bpm"].mean()
        assert end < peak

    def test_stable_has_low_variance(self, trends):
        stable = trends[trends["trend_mode"] == "stable"]
        per_patient_std = stable.groupby("patient_id")["resting_hr_bpm"].std()
        # daily noise only (no drift) -- std should be small relative to a resting HR baseline
        assert per_patient_std.mean() < 5


def test_generation_is_deterministic_given_seed():
    a = generate_patients(n=50, seed=123)
    b = generate_patients(n=50, seed=123)
    pd.testing.assert_frame_equal(a, b)
