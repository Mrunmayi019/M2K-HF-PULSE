# Data Provenance

Single source of truth for every clinical threshold / distribution parameter used anywhere in this
codebase. Every number used in `src/data_synthesis/`, `src/rules.py`, or later ML/analytics code
must trace back to a row here. No magic numbers in code (see CLAUDE.md "Known Gotchas").

Never real patient data — clinical baselines are synthetic, derived from cited papers/Kaggle sets
(see CLAUDE.md "Locked Phase 0 Decisions").

## Status

This table is seeded with the example figures already quoted in the project's planning doc
(`/Users/prakul/Desktop/Pulse-dock/digital-twin-info/M2K PULSE.pdf`). Full extraction from the
complete text of the 4 source papers is **not yet done** — only the values the planning doc itself
already gave as concrete examples are populated below. Rows marked `TODO` still need the source
paper consulted directly before use in any downstream model.

## Reference Table

| Parameter | Value / Range | Source Key | Citation | Status |
|---|---|---|---|---|
| Age (general HF cohort) | mean 61.49, SD 13.88 | `sinha_2024` | Sinha et al. | seeded from planning doc example |
| Ejection Fraction, HFrEF | mean 30%, range 15–40% | `sinha_2024` | Sinha et al. | seeded from planning doc example |
| NT-proBNP diagnostic cutoff, age < 50 | > 450 pg/mL | `bhosale_2024` | Bhosale et al. | seeded from planning doc example |
| NT-proBNP diagnostic cutoff, age 50–75 | > 900 pg/mL | `bhosale_2024` | Bhosale et al. | seeded from planning doc example |
| NT-proBNP diagnostic cutoff, age > 75 | > 1800 pg/mL | `bhosale_2024` | Bhosale et al. | seeded from planning doc example |
| BNP (not NT-proBNP) general threshold | > 35 pg/mL | (AHA/ACC 2022 guideline, Stage B criterion) | 2022 AHA/ACC/HFSA Guideline | from planning doc, needs page ref |
| LVEF Stage B threshold | ≤ 40% | (AHA/ACC 2022 guideline) | 2022 AHA/ACC/HFSA Guideline | from planning doc, needs page ref |
| Height/weight/BMI distributions by sex | — | — | Kaggle dataset #1 (unspecified) | TODO — dataset not yet identified/loaded |
| Resting HR, SpO2, sleep, steps baseline distributions | — | — | wearable HRV/sleep dataset | TODO — dataset not yet identified/loaded |
| Ohte et al. parameters | — | — | Ohte et al. | TODO — not yet extracted |
| NYHA class ↔ METs mapping | I: >7 METs, II: 5–7, III: 2–5, IV: <2 | — | heart.org / AHA NYHA classification | seeded from planning doc |

## How to extend this file

1. Add a row before using any new number in code.
2. Prefer citing the exact page/table of the source paper once you have it, not just the paper name.
3. Update `src/data_synthesis/reference_stats.yaml` in lockstep — that file must mirror this table's
   `sourced` values exactly (see the `source` key on every entry there).
