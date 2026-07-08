import SeverityGauge from './SeverityGauge.jsx'
import { scenarioMeta, fmt1, trendDirection } from '../../utils/format.js'

// MAP isn't a wearable-derived vital (it's only computed inside a Pulse simulation run, and isn't
// persisted per-horizon -- see the Phase 7 plan's "redesign around real fields" decision), so the
// 3 headline metric cards use the 3 clinically-central *wearable* vitals instead of the design's
// HR/SpO2/MAP trio.
const HEADLINE_VITALS = [
  { key: 'resting_hr_bpm', label: 'Heart Rate', unit: 'bpm' },
  { key: 'spo2_pct', label: 'SpO2', unit: '%' },
  { key: 'weight_kg', label: 'Weight', unit: 'kg' },
]

function metricCard(key, label, unit, wearable, slopes) {
  const value = wearable?.[key]
  const slope = slopes?.[key]
  const { arrow, worsening } = trendDirection(key, slope)
  return (
    <div className="metriccard" key={key}>
      <div>
        <div className="metriclabel">{label}</div>
        <div className="metricval">
          {value === undefined || value === null ? '—' : fmt1(value)}
          <span className="metricunit">{unit}</span>
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div className="trendbadge" style={{ color: worsening ? '#EF4444' : '#22C55E' }}>
          {arrow} {slope === undefined || slope === null ? '' : `${fmt1(Math.abs(slope))}/day`}
        </div>
      </div>
    </div>
  )
}

export default function CurrentConditionPanel({ assessment, wearable }) {
  const scenario = scenarioMeta(assessment?.scenario_type)
  const severity = assessment?.severity ?? null

  return (
    <div className="section">
      <div className="sectitle">
        Current Condition <span className="sub">detected scenario &amp; live vitals</span>
      </div>
      <div className="grid2">
        <div className="card condleft">
          <div className="scenariorow">
            <div className="scenicon" style={{ background: `${scenario.color}1A`, color: scenario.color, fontSize: 20 }}>
              {scenario.icon}
            </div>
            <div>
              <div className="scenname">{assessment ? scenario.name : 'Not yet classified'}</div>
              <div className="scensub">Classified from wearable input · last 21-day window</div>
            </div>
          </div>
          <div className="gaugewrap">
            <SeverityGauge severity={severity} color={scenario.color} />
            <div>
              <div style={{ fontSize: 11, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700 }}>
                Severity Index
              </div>
              <div style={{ fontSize: 26, fontWeight: 800, fontFamily: "'JetBrains Mono', monospace" }}>
                {severity === null ? '—' : severity.toFixed(2)}
              </div>
              <div style={{ fontSize: 11.5, color: 'var(--muted)' }}>of 1.0 scale</div>
            </div>
          </div>
          <div className="efbnprow">
            <div className="minicard">
              <div className="minival">{assessment?.ejection_fraction_pct ?? '—'}%</div>
              <div className="minilabel">Ejection Fraction</div>
            </div>
            <div className="minicard">
              <div className="minival">{assessment?.nt_probnp_pg_ml ?? '—'}</div>
              <div className="minilabel">BNP pg/mL</div>
            </div>
          </div>
        </div>
        <div className="card metriccol">
          {HEADLINE_VITALS.map(({ key, label, unit }) => metricCard(key, label, unit, wearable, assessment?.vital_slopes))}
        </div>
      </div>
    </div>
  )
}
