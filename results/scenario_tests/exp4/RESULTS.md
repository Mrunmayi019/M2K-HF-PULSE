# Experiment 4 results (seeds 48–53, 60/60 runs complete)

Scored against `PREREGISTRATION.md` (commit `9a6b290`) and `AMENDMENT_1.md` (commit `1db94de`) by
`exp4_analyze.py`. Experiment 2's saved results are the control arm. Full numbers: `exp4_analysis.json`.
Failed Pulse days count as no alert (primary). Counting them as alerts is reported where it changes a number.

## Run notes

- Batch ran 2026-10-26 13:40 to 2026-10-27 04:36 IST, from commit `1db94de`. All 60 jobs exited cleanly.
- **Interruption.** The Mac went to sleep at 19:04 on 2026-10-26 (lid closed, on battery) and stayed asleep until
  about 22:30. Two jobs were running: P05 seeds 48 and 49. As §7 requires, both were rerun from day 1 after the batch
  into a separate directory, and the reruns are the scored files here. The paused originals are kept in `interrupted_by_sleep/`.
  The reruns match the originals on every value except `predicted_severity`, which differs in the last bits on 3
  days per series (see I1). No other job ran during the sleep.

## Integrity checks

| Check | Result | Verdict |
|---|---|---|
| I1 classifier label identical to Exp 2 | 0 of 1,260 days differ | hold |
| I1 classifier severity identical to Exp 2 | 375 of 1,260 days differ, max \|Δ\| 4.4 × 10⁻¹⁶ | **does not hold bit for bit** (see below) |
| I2 Pulse output on days 1–7 identical to Exp 2 | 0 of 420 days differ (HR, MAP, CO, risk score; max \|Δ\| 0) | hold |
| I3 refreshes due vs performed | 174 due, 174 performed, 0 errors | hold |

**I1 severity.** The differences are floating-point noise at the level of 1–2 units in the last place. They are run to
run, not caused by the flag: the two P05 reruns show the same kind of difference against the first Exp 4 runs. The
cause was not investigated. They had no effect on Pulse: days 1–7 include such differences (e.g. 17 on day 1) and
their Pulse output is still identical to Exp 2 (I2).

**174 refreshes, not 180.** A failed Pulse day saves no state, so it delays the series' next refresh (§2). Refresh
days: day 7 in 60 series, day 14 in 54, days 15–18 in one series each, and day 21 in 56 (this includes the second
refresh of P07 seeds 50 and 52). Six series had 2 refreshes, not 3. All six are P07 or P10 series with failed days.

## Primary and secondary outcomes

| Outcome | Exp 2 | **Exp 4** | Predicted | Verdict |
|---|---|---|---|---|
| P1 A (n = 123): median MAP drift [IQR] | — | **+0.2** [+0.1, +0.2] mmHg | within ±3 | hit |
| P1 A: median HR drift [IQR] | — | **−3.0** [−3.7, −2.0] bpm | −10 to +3 | hit |
| P1 B (n = 35): median MAP drift [IQR]; share ≤ −15 | — | **−29.3** [−32.3, −27.2] mmHg; **100%** | ≤ −15; ≥ 75% | hit |
| P1 B: median HR drift [IQR] | — | **−28.2** [−30.6, −25.8] bpm | ≤ −10 | hit |
| P1 C (n = 16): median MAP drift [IQR] | — | **−29.9** [−30.5, −28.6] mmHg | ≤ −15 | hit |
| P2 post-onset deployed alert days, should_catch | 268 | **140** (164 with failed days as alerts) | 100–190 (estimate 136) | hit |
| P3 sensitivity | 24/30 | **24/30** | 23–25/30 | hit |
| P3 pre-onset alerts | 10.0/100, 7/30 | **10.0/100, 7/30** | unchanged | hit |
| P3 strict detection | 17/30 | **17/30** | 16–18/30 | hit |
| P3 false alerts / 100 patient-days [95% CI] | 4.8 [1.6, 7.9] | **10.1** [3.2, 16.9] | 3.0–6.0 | **miss** (higher) |
| P3 quiet series silent | 12/18 | **12/18** (P01 6/6, P09 6/6, P08 0/6) | 12/18 | hit |
| P3 label accuracy | 37.1% | **37.1%** | 37.1% | hit |
| P4 Pulse-HIGH days 8–21: should_catch / should_stay_quiet | 330 / 71 | **82 / 65** | 80–200 / 50–80 | hit (catch at lower edge) |
| Reset-eligible Exp 2 alert days still alerting | — | **0 of 132** (0%) | ≤ 20% | hit |
| Other Exp 2 alert days (exertion since refresh) still alerting | — | **55 of 90** (61%) | ≥ 50% | hit |
| Stuck-state share of HIGH days (end HR < 50) | 358/475 (75%) | **116/221 (52%)** | ≥ 60% | **miss** (lower) |
| Anchor: HIGH days with MAP drop ≥ 20 mmHg vs chain baseline | — | **218/221 (98.6%)**, median 28.2 mmHg | ≥ 80% | hit |
| Collapse days (end HR < 30 or MAP < 50), series (Amendment 1) | 16, 1 | **2, 1** | ≤ 16 | hit |

Counting failed days as alerts gives sensitivity 25/30 and strict detection 18/30 in both experiments. False alerts,
pre-onset alerts and quiet series silent do not change. Drift group sizes were predicted at about 123 / 38 / 19. The
results are 123 / 35 / 16, because six refreshes were delayed or missing.

## Findings not in the predictions

- **Failed Pulse days: 24 in 6 series (P07 19, P10 5); Exp 2 had 3 in 1 series (P07).** Every failure is the same
  Pulse error (`PulseScenarioDriver exited 1 … unfiltered fatal`) after 4–9 s of wall time. All fall on
  `cardiac_stress` or `acute_deterioration` days with severity 0.86–0.92, after the series' first refresh. 3 of the
  24 are Exp 2's own failed days (P07 seed 48, days 13–15). The other 21 completed in Exp 2 with the same label and
  severity, so they fail only on the refreshed twin. The cause was not investigated. The failures are not linked to
  the sleep: P07 and P10 ran after it. The 19 P07 failures are one reason P07's post-onset alert days fall from 90 to 20 (39 with failed days
  counted as alerts).
- **Why false alerts doubled: all of the increase is P08.** False-alert days rise from 18 to 38 in should_stay_quiet
  series on days 8–21, and every extra day is P08 (+3 to +5 per seed; P01 and P09 stay silent). In Exp 2, P08's
  twin turns HIGH on day 9–12 and stays HIGH to day 21 in every seed. The deployed alert fires for 3 days, and then the C3 guard
  (`C3_STREAK_THRESHOLD_DAYS = 3`, baseline-dominated HIGH streak without instability) downgrades it to WATCH. In
  Exp 4, the day-14 refresh clears the stuck state. P08's next exertion days push it back to HIGH, a new streak
  starts, and the alert fires again (days 16–18 in all 6 seeds; seed 50 also on days 13–14). The same thing adds alert days in some P06 series,
  which is why P06's post-onset alert days rise from 28 to 35 while P04, P05, P07 and P10 fall.
- **Drift outliers.** On four refresh days the resumed twin ended at HR 112–160 bpm (P05 seed 52 day 7, P06 seed 52
  days 7 and 14, P06 seed 53 day 14; only the last had Exercise that day). They have positive HR drift (+41 to +84 bpm)
  and CO drift of +3,300 to +3,800 mL/min. One (P10 seed 49, day 7) is on a collapse day:
  −63 bpm, −54 mmHg. The day-7 refresh clears that series' collapse; in Exp 2 it ran on to day 21.

## What this means (by the pre-registered reading)

P2 is in range and sensitivity, pre-onset alerts, strict detection, quiet series silent and label accuracy are
unchanged. By the reading committed in §6, a large part of the twin's sustained post-onset alerting comes from the
stuck engine state, and first detection does not depend on it. Every one of the 132 reset-eligible Exp 2 alert days
is gone. Drift without exertion (group A) is within ±3 mmHg, so the continuous twin does not drift on its own.

Two limits on that reading. First, the drop in P2 is 48% (268 → 140), and 39% (271 → 164) with failed days counted
as alerts. That is less than the "most" in the §6 wording, which assumed the remaining alerts would not include new
ones caused by the refresh itself. Second, the refresh doubles false alerts in P08 (miss on P3 false alerts). It
restarts the C3 guard's streak, and it adds Pulse failures at high cardiac_stress severity. The weekly refresh is not
a free fix for the deployed system.

The stuck-state share miss (52% vs ≥ 60%) means the HIGH days left are less often the low-HR stuck state than
predicted. The refresh removes stuck HIGH days far more than other HIGH days: 358 → 116 (−68%) against 117 → 105
(−10%).
