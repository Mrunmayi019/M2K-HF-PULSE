"""Research-feature flags (feature/wire-research-features). Every flag defaults to OFF, and with all
of them off the API returns exactly what main did before they existed
(tests/test_flags_off_parity.py).

Read from the environment on every call rather than once at import, so a test can flip a flag
with monkeypatch and a deployment can change one with a restart and no code change.

| Env var                      | Values                   | Default |
|------------------------------|--------------------------|---------|
| PIPELINE_MODE                | fresh / continuous       | fresh   |
| ENABLE_BCG_MODIFIERS         | 1/true/yes/on, else off  | off     |
| ENABLE_HR_BASELINE           | 1/true/yes/on, else off  | off     |
| ENABLE_ALERT_HYSTERESIS      | 1/true/yes/on, else off  | off     |
| ENABLE_SCENARIO_PERSISTENCE  | 1/true/yes/on, else off  | off     |
| BASELINE_REFRESH_DAYS        | integer >= 0             | 0 (off) |

BASELINE_REFRESH_DAYS only acts in continuous mode. The baseline anchor it builds on is not a flag:
continuous mode always records it (see continuous_state_pipeline.py).

The README's feature-flag table says what each one does and how much evidence is behind it.
"""
from __future__ import annotations

import os
from typing import Literal

PipelineMode = Literal["fresh", "continuous"]
PIPELINE_MODES: tuple[str, ...] = ("fresh", "continuous")

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


def _bool_flag(name: str) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"{name}={raw!r} is not a recognised on/off value (use 1/0, true/false, yes/no, on/off)")


def pipeline_mode() -> PipelineMode:
    raw = os.environ.get("PIPELINE_MODE", "fresh").strip().lower() or "fresh"
    if raw not in PIPELINE_MODES:
        raise ValueError(f"PIPELINE_MODE={raw!r} must be one of {PIPELINE_MODES}")
    return raw  # type: ignore[return-value]


def bcg_modifiers_enabled() -> bool:
    return _bool_flag("ENABLE_BCG_MODIFIERS")


def hr_baseline_enabled() -> bool:
    return _bool_flag("ENABLE_HR_BASELINE")


def alert_hysteresis_enabled() -> bool:
    return _bool_flag("ENABLE_ALERT_HYSTERESIS")


def scenario_persistence_enabled() -> bool:
    return _bool_flag("ENABLE_SCENARIO_PERSISTENCE")


DEFAULT_BASELINE_REFRESH_DAYS = 0


def baseline_refresh_days() -> int:
    """How many saved states a continuous chain holds before it is re-baselined from the patient
    file. 0 (the default) turns the refresh off; the anchor is recorded either way. Experiment 3
    ran with 7."""
    raw = os.environ.get("BASELINE_REFRESH_DAYS", "").strip()
    if raw == "":
        return DEFAULT_BASELINE_REFRESH_DAYS
    try:
        days = int(raw)
    except ValueError:
        days = -1
    if days < 0:
        raise ValueError(f"BASELINE_REFRESH_DAYS={raw!r} must be a whole number >= 0")
    return days


def all_flags() -> dict:
    """Current value of every flag, for the dashboard and logs. BASELINE_REFRESH_DAYS is listed
    only while it is above 0: the dashboard hides its twin-state panel when every listed value is
    'fresh' or false (frontend/src/utils/twinState.js). It is still validated either way."""
    refresh_days = baseline_refresh_days()
    flags = {
        "PIPELINE_MODE": pipeline_mode(),
        "ENABLE_BCG_MODIFIERS": bcg_modifiers_enabled(),
        "ENABLE_HR_BASELINE": hr_baseline_enabled(),
        "ENABLE_ALERT_HYSTERESIS": alert_hysteresis_enabled(),
        "ENABLE_SCENARIO_PERSISTENCE": scenario_persistence_enabled(),
    }
    if refresh_days > 0:
        flags["BASELINE_REFRESH_DAYS"] = refresh_days
    return flags


def validate_all() -> None:
    """Called once at app startup so a typo in an env var fails loudly instead of on the first
    wearable sync."""
    all_flags()
