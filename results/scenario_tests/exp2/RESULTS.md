# Experiment 2 results (seeds 48–53, 60/60 runs complete)

Scored against `PREREGISTRATION.md` (commit f353bd0) by `exp2_analyze.py`; Experiment 1 is scored the
same way. Full numbers: `exp2_analysis.json`. 3 failed Pulse days in each experiment, counted as no alert.

| Outcome (deployed system unless noted) | Exp 1 | **Exp 2** | Predicted | Verdict |
|---|---|---|---|---|
| Label accuracy | 17.6% | **37.1%** | 30–45% | hit |
| Sensitivity (co-primary) | 21/30 | **24/30** | 18–26/30 | hit |
| Pre-onset alerts (co-primary) | 31.7/100 days, 7/30 series | **10.0/100, 7/30** | 10–30/100, 6–14/30 | hit (at lower edge) |
| Strict detection (secondary) | 14/30 | **17/30** | 6–12/30, likely lower | **miss** (higher) |
| Quiet series silent | 10/18 | **12/18** (P01 6/6, P09 6/6, P08 0/6) | 11–13/18 | hit |
| False alerts / 100 patient-days | 8.7 | **4.8** [1.6, 7.9] | lower than Exp 1 | hit |
| Classifier severity > 0.55: strict | 30/30 | **30/30** | ≥ 26/30 | hit |
| Classifier severity > 0.55: false alerts | 8.5 | **10.1** | ≤ 10 | **miss** (narrow) |

Per patient: P04 and P07 labels stayed at 0% as predicted. P05 was caught in 2/6 series (the dry run implied 0).
Why strict detection missed: the predicted rise in series that alert before onset did not happen (7/30 in both
experiments), while sensitivity rose by 3, so strict detection = 24 − 7 = 17. Counting failed days as alerts changes only sensitivity (25/30)
and strict detection (18/30). The classifier at 0.55 still catches all 30 series; the deployed system now has
half its false-alert rate.
