"""Experimental patient personalisation (feature/wire-research-features): BCG-derived compliance
modifiers (ENABLE_BCG_MODIFIERS) and a clinician-entered resting heart-rate baseline
(ENABLE_HR_BASELINE). Both default OFF.

Nothing here is new modelling. bcg_to_cardiovascular_modifiers() and build_patient_file()'s
hr_baseline_bpm are used exactly as they were in the subject-14/102 validation
(docs/bcg_validation_note.md), with the same reference values and coefficients. This module only
decides whether to call them and records that it did.

Where the inputs come from: optional fields on the clinical report, entered by a clinician.
hr_baseline_bpm is a measured resting HR from a clinical source (the validation used each
subject's clinical-sheet HR). It is NOT derived from wearable data -- no derivation rule exists
and none is invented here.

Accepted ranges are exactly what the two calibration subjects cover (Zhan et al. 2025 BCG
dataset; values from scripts/bcg_hr_baseline_experiment.py / docs/bcg_validation_note.md):

    subject 14:  R-J 233.0 ms, I-J 1.172, J-K 1.496, clinical-sheet HR 77 bpm
    subject 102: R-J 175.0 ms, I-J 1.061, J-K 1.162, clinical-sheet HR 115 bpm

Anything outside [min, max] of those two is rejected at the API (422) rather than extrapolated.
Pulse itself clamps HeartRateBaseline to 50-110 bpm, so an entered 111-115 is simulated at 110,
the same as subject 102 was; the stored record shows both values.
"""
from __future__ import annotations

from typing import Optional

from src.patient_builder.patient_file import bcg_to_cardiovascular_modifiers, pulse_eligible_hr_baseline

# (min, max) over the two calibration subjects -- see module docstring.
RJ_INTERVAL_MS_RANGE = (175.0, 233.0)
IJ_AMPLITUDE_RANGE = (1.061, 1.172)
JK_AMPLITUDE_RANGE = (1.162, 1.496)
HR_BASELINE_BPM_RANGE = (77.0, 115.0)

BCG_FIELDS = ("rj_interval_ms", "ij_amplitude", "jk_amplitude")

PERSONALISATION_CAVEAT_MESSAGE = (
    "Experimental personalisation applied ({what}). Calibrated on 2 subjects from one dataset "
    "(Zhan et al. 2025 multi-pathology BCG dataset); BCG amplitude units are specific to that "
    "dataset and are not comparable with other sensors. Not validated against outcomes. In the "
    "original validation, setting the HR baseline made stroke volume match worse in both subjects "
    "(docs/bcg_validation_note.md)."
)


def report_has_bcg(report) -> bool:
    return report is not None and all(getattr(report, f, None) is not None for f in BCG_FIELDS)


def bcg_modifiers_for(report) -> Optional[dict]:
    """bcg_to_cardiovascular_modifiers() with its own default reference values (subject 102), or
    None when the report carries no BCG features."""
    if not report_has_bcg(report):
        return None
    return bcg_to_cardiovascular_modifiers(report.rj_interval_ms, report.ij_amplitude, report.jk_amplitude)


def bcg_record(report, modifiers: dict, applied: bool, note: Optional[str] = None) -> dict:
    record = {
        "rj_interval_ms": report.rj_interval_ms,
        "ij_amplitude": report.ij_amplitude,
        "jk_amplitude": report.jk_amplitude,
        "modifiers": modifiers,
        "applied": applied,
    }
    if note:
        record["note"] = note
    return record


def hr_baseline_record(requested_bpm: float, applied: bool, note: Optional[str] = None) -> dict:
    record = {
        "requested_bpm": requested_bpm,
        "simulated_bpm": pulse_eligible_hr_baseline(requested_bpm),
        "applied": applied,
    }
    if note:
        record["note"] = note
    return record


def personalisation_caveat(record: Optional[dict]) -> Optional[str]:
    """The caveat text for a SimulationRun.personalisation_json record, or None if nothing in it
    actually reached Pulse."""
    if not record:
        return None
    parts = []
    if record.get("bcg", {}).get("applied"):
        parts.append("BCG compliance modifiers")
    if record.get("hr_baseline", {}).get("applied"):
        parts.append("resting heart-rate baseline")
    if not parts:
        return None
    return PERSONALISATION_CAVEAT_MESSAGE.format(what=" and ".join(parts))
