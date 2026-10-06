// The hero card's one-line summary, kept as a pure function so it can be unit-tested without a
// browser (src/utils/heroSummary.test.js, `npm test`).
//
// Keyed on `assessment.alert.level` (decide_alert(), the twin) -- NOT risk_bucket directly -- so a
// C3-downgraded HIGH reads as WATCH here too. When the twin and the ML-severity signal disagree
// (`signals_disagree`, fix/alert-both-signals), no twin-only reassurance is shown: "stable -- no
// action needed" next to "ML model flags this patient" would contradict itself.
export const ALERT_SUMMARY = {
  ALERT: 'Significant deterioration detected — clinical follow-up is recommended today.',
  WATCH: 'Some signs of strain detected — monitor closely and review symptoms.',
  NONE: 'This patient is stable — no action needed beyond routine monitoring.',
}

export const SIGNALS_DISAGREE_SUMMARY = 'Signals disagree — review this patient.'

export const NO_ASSESSMENT_SUMMARY = 'Waiting for the first completed simulation.'

export function heroSummary(alertLevel, signalsDisagree) {
  if (!alertLevel) return NO_ASSESSMENT_SUMMARY
  if (signalsDisagree === true) return SIGNALS_DISAGREE_SUMMARY
  return ALERT_SUMMARY[alertLevel]
}
