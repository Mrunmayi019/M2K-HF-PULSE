import EcgWave from './EcgWave.jsx'
import { riskColor } from '../../utils/format.js'

// Keyed on `assessment.alert.level` (fix/unified-alert-decision) -- NOT risk_bucket directly.
// risk_bucket still drives the badge's color (kept for visual continuity across LOW/MODERATE/
// HIGH), but whether this card reads as urgent is the backend's single decide_alert() decision,
// so a C3-downgraded HIGH (sustained baseline-only elevation, no corroborating acute signal)
// reads as WATCH here too, not as a repeated urgent alert.
const ALERT_SUMMARY = {
  ALERT: 'Significant deterioration detected — clinical follow-up is recommended today.',
  WATCH: 'Some signs of strain detected — monitor closely and review symptoms.',
  NONE: 'This patient is stable — no action needed beyond routine monitoring.',
}

const ALERT_WARNING = {
  ALERT: 'This projection indicates rapid decompensation risk. This is a decision-support estimate only — seek clinical evaluation promptly.',
  WATCH: 'Trends suggest early strain. A closer review may be warranted at the next visit.',
  NONE: 'No alert from the latest assessment. Continue daily wearable syncing.',
}

// Shown for EVERY scenario_type when the backend reports EF was Tier-1-defaulted (ef_is_fallback),
// not only for the fluid_overload caveat: the default feeds both the classifier and the simulated
// heart, so any scenario can read as lower-risk than it is (docs/gap_report.md G3).
function efDefaultWarning(efPct) {
  const value = efPct === null || efPct === undefined ? '' : ` (${efPct}%)`
  return (
    `EF not measured, healthy default${value} used. The simulated heart is structurally normal, ` +
    'so this risk level may understate a sick patient. A measured ejection fraction would change it.'
  )
}

function Banner({ text, background, color, border }) {
  return (
    <div className="warnbanner" style={{ background, color, border }}>
      <svg width="15" height="15" viewBox="0 0 24 24" fill="none" style={{ flex: 'none', marginTop: 1 }}>
        <path d="M12 3l10 18H2L12 3z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
        <path d="M12 10v4M12 17.5v.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      </svg>
      <div>{text}</div>
    </div>
  )
}

// alert.source === 'c3_downgraded': a HIGH risk_bucket that's been driven by baseline_deficit_score
// alone, with no corroborating instability_flag, for more than 3 consecutive days -- downgraded
// to WATCH (never to NONE) rather than repeating the same urgent alert every day with nothing new
// to act on. Worded distinctly from the plain MODERATE-driven WATCH case above.
const C3_DOWNGRADED_WARNING =
  'Risk score has been persistently elevated from a baseline shift alone, with no corroborating ' +
  'acute signal, for several days — downgraded from an urgent alert pending further confirmation. ' +
  'This is a decision-support estimate only.'

export default function HeroStatusCard({ assessment, patientLabel }) {
  const riskBucket = assessment?.risk_bucket ?? null
  const alertLevel = assessment?.alert?.level ?? null
  const alertSource = assessment?.alert?.source ?? null
  const color = riskColor(riskBucket)
  const isAlert = alertLevel === 'ALERT'
  const badgeLabel =
    alertLevel === 'WATCH' ? 'WATCH' : riskBucket ? `${riskBucket} RISK` : 'NO ASSESSMENT YET'
  // The risk warning and the caveats are separate banners: risk_caveats is always populated for a
  // completed run (it carries the ECG reference-template disclaimer), so letting it replace the
  // risk warning -- as `risk_caveats || warning` did -- hid every risk-level warning.
  const riskWarning =
    alertSource === 'c3_downgraded' ? C3_DOWNGRADED_WARNING : alertLevel ? ALERT_WARNING[alertLevel] : null
  const efWarning = assessment?.ef_is_fallback ? efDefaultWarning(assessment?.ejection_fraction_pct) : null
  const caveats = assessment?.risk_caveats || null
  const tone = {
    background: `${color}0F`,
    color: color === '#22C55E' ? '#166534' : color === '#EAB308' ? '#854D0E' : '#B91C1C',
    border: `1px solid ${color}33`,
  }

  return (
    <div className="section">
      <div
        className={`card hero ${isAlert ? 'risk-high' : ''}`}
        style={{ borderColor: `${color}55` }}
      >
        <div className="herotop">
          <div>
            <div className="riskbadge" style={{ background: `${color}1A`, color }}>
              <span className="pill-dot" />
              {badgeLabel}
            </div>
            <div className="badgerow">
              {assessment?.nyha_class && <span className="tag">NYHA Class {assessment.nyha_class}</span>}
            </div>
            <div className="heroname">{patientLabel}</div>
            <div className="herosummary">
              {alertLevel ? ALERT_SUMMARY[alertLevel] : 'Waiting for the first completed simulation.'}
            </div>
          </div>
          <div className="ecgwrap">
            <EcgWave color={color === '#64748B' ? '#94A3B8' : color} />
          </div>
        </div>
        {riskWarning && <Banner text={riskWarning} {...tone} />}
        {efWarning && (
          <Banner text={efWarning} background="#EAB3081A" color="#854D0E" border="1px solid #EAB30855" />
        )}
        {caveats && (
          <Banner text={caveats} background="var(--surface-2, #64748B0F)" color="var(--muted)" border="1px solid #64748B33" />
        )}
      </div>
    </div>
  )
}
