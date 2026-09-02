import { useMemo } from 'react'
import TrendChart from '../trends/TrendChart.jsx'
import { riskColor } from '../../utils/format.js'

const HORIZON_KEYS = ['7', '14', '30']
const HORIZON_LABELS = { 0: 'Now', 7: '+7d', 14: '+14d', 30: '+30d' }

function HorizonCard({ label, nowClass, severity, riskBucket }) {
  const color = riskBucket ? riskColor(riskBucket) : '#64748B'
  return (
    <div className="projcol">
      <div className={`projhead ${nowClass}`}>{label}</div>
      <div className="projrow">
        <div className="projval">{severity === null || severity === undefined ? '—' : severity.toFixed(2)}</div>
        <div className="projlabel">Severity Index</div>
      </div>
      {riskBucket && (
        <div className="projrisk" style={{ background: `${color}1A`, color }}>
          {riskBucket} RISK
        </div>
      )}
    </div>
  )
}

// days_to_next_stage is a linear-extrapolation day-count (src/analytics/deterioration_rate.py),
// not a probability -- shown as a 30-day-window progress bar (sooner = more filled) rather than
// relabeling it as a percentage it was never computed to be.
function daysToBarPct(days) {
  if (days === null || days === undefined) return 0
  return Math.round((1 - Math.min(days, 30) / 30) * 100)
}

export default function ForwardProjectionPanel({ assessment, horizons }) {
  const daysToNext = assessment?.days_to_next_stage ?? null
  // days_to_next_stage.py returns None for two different reasons this panel used to collapse into
  // the single word "stable": a genuinely flat/improving trend, OR the patient already being at the
  // highest (HIGH) tier with nowhere higher to project a crossing date for -- the second case can
  // still be actively worsening (see docs: a HIGH patient's severity climbing 0.50->0.57 read as
  // "stable" on screen, exactly backwards). Risk_bucket is the one signal already exposed here that
  // distinguishes them without a backend change.
  const atCeiling = assessment?.risk_bucket === 'HIGH' && daysToNext === null
  const pct = daysToBarPct(daysToNext)
  const barColor = assessment?.risk_bucket ? riskColor(assessment.risk_bucket) : 'var(--teal)'

  const trajectory = useMemo(() => {
    const points = [{ x: 0, y: assessment?.severity ?? null }]
    for (const key of HORIZON_KEYS) {
      const h = horizons?.[key]
      points.push({ x: Number(key), y: h?.projected_severity ?? null })
    }
    return points.filter((p) => p.y !== null && p.y !== undefined)
  }, [assessment, horizons])

  return (
    <div className="section">
      <div className="sectitle">
        Forward Projection <span className="sub">digital twin trajectory</span>
      </div>
      <div className="card" style={{ padding: '20px 24px 8px' }}>
        <div className="projexplainer">
          Each point is a fresh Pulse simulation of this patient's projected future state at that
          severity — not a curve fit through past readings.
        </div>
        {trajectory.length >= 2 && (
          <TrendChart
            data={trajectory}
            color={barColor}
            height={120}
            formatX={(v) => HORIZON_LABELS[v] ?? `+${v}d`}
            formatY={(v) => v.toFixed(2)}
          />
        )}
      </div>
      <div className="card" style={{ marginTop: 14 }}>
        <div className="projgrid">
          <HorizonCard label="Now" nowClass="now" severity={assessment?.severity ?? null} riskBucket={assessment?.risk_bucket ?? null} />
          {HORIZON_KEYS.map((key) => {
            const h = horizons?.[key]
            return (
              <HorizonCard
                key={key}
                label={`+${key} Days`}
                nowClass=""
                severity={h?.projected_severity ?? null}
                riskBucket={h?.risk_bucket ?? null}
              />
            )
          })}
        </div>
        <div className="probwrap">
          <div className="probhead">
            <span>Projected time to next risk tier</span>
            <b>{daysToNext !== null ? `${daysToNext}d` : atCeiling ? 'at ceiling' : 'stable'}</b>
          </div>
          <div className="probtrack">
            <div className="probfill" style={{ width: `${pct}%`, background: barColor }} />
          </div>
        </div>
      </div>
    </div>
  )
}
