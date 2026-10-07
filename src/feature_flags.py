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


def all_flags() -> dict:
    """Current value of every flag, for the dashboard and logs."""
    return {
        "PIPELINE_MODE": pipeline_mode(),
        "ENABLE_BCG_MODIFIERS": bcg_modifiers_enabled(),
        "ENABLE_HR_BASELINE": hr_baseline_enabled(),
        "ENABLE_ALERT_HYSTERESIS": alert_hysteresis_enabled(),
        "ENABLE_SCENARIO_PERSISTENCE": scenario_persistence_enabled(),
    }


def validate_all() -> None:
    """Called once at app startup so a typo in an env var fails loudly instead of on the first
    wearable sync."""
    all_flags()
