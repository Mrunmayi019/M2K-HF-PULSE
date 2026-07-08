import { riskColor } from '../../utils/format.js'

const HORIZON_KEYS = ['7', '14', '30']

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
  const pct = daysToBarPct(daysToNext)
  const barColor = assessment?.risk_bucket ? riskColor(assessment.risk_bucket) : 'var(--teal)'

  return (
    <div className="section">
      <div className="sectitle">
        Forward Projection <span className="sub">digital twin trajectory</span>
      </div>
      <div className="card">
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
            <b>{daysToNext === null ? 'stable' : `${daysToNext}d`}</b>
          </div>
          <div className="probtrack">
            <div className="probfill" style={{ width: `${pct}%`, background: barColor }} />
          </div>
        </div>
      </div>
    </div>
  )
}
