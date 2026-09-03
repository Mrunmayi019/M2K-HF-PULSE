import TrendChart from './TrendChart.jsx'
import { DashboardSkeleton } from '../shared/Skeleton.jsx'
import ErrorState from '../shared/ErrorState.jsx'
import { useTrends } from '../../hooks/useTrends.js'
import { VITAL_ORDER, vitalMeta, fmt1, riskColor, scenarioMeta, formatDateTime, avatarFromId } from '../../utils/format.js'

const SHORT_DATE = (iso) => new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' })

function RiskHistoryTable({ assessments }) {
  // "Day N" is this row's POSITION in ascending created_at order -- not a backend-derived field.
  // No API field currently links a RiskAssessment to the simulated day/PulseState that produced it
  // (no FK, no stored day-index -- src/api/continuous_state_pipeline.py never writes one, and
  // PulseState isn't even exposed by any endpoint). This is only accurate for a patient whose
  // entire history came from one unbroken continuous-sync sequence with nothing else mixed in --
  // for a patient with any old-pipeline (from-scratch) assessment interleaved, "Day N" here would
  // NOT correspond to the Nth continuous-sync day (see docs/continuous_state_sync_status.md
  // investigation, 2026-09-03).
  const withDayNumbers = assessments.map((a, i) => ({ ...a, _dayNumber: i + 1 }))

  // Diagnosed 2026-09-03: a continuous-state-sync demo patient whose 21-day wearable window was
  // seeded once and never re-synced between simulated days shows the EXACT same severity on every
  // row -- run_daily_continuous_pipeline() does recompute it fresh each call, it's just that the
  // window it reads never changed, so the prediction can't either. That's not a display bug, but
  // showing an unchanging number next to 6 different dates reads as "severity isn't tracking this
  // patient", which is misleading. For every other patient (advanced via the normal /wearable-sync
  // pipeline, where each new day's reading genuinely shifts the rolling window) severity DOES vary
  // meaningfully run to run -- hiding the column for them would throw away real signal. So this is
  // scoped per-patient: only hide it when this patient's own history shows zero variation, using
  // the same 2-decimal rounding the column displays (a flat display value is what reads as static
  // to a viewer, even if the raw floats differ in the 4th decimal).
  const displayedSeverities = new Set(
    assessments.filter((a) => a.severity !== null && a.severity !== undefined).map((a) => a.severity.toFixed(2))
  )
  const severityIsStatic = assessments.length > 1 && displayedSeverities.size <= 1

  return (
    <div className="card tablewrap">
      <table className="vt">
        <thead>
          <tr>
            <th>Day</th>
            <th>Date</th>
            <th>Scenario</th>
            {!severityIsStatic && <th>Severity</th>}
            <th>Risk</th>
            <th>NYHA</th>
          </tr>
        </thead>
        <tbody>
          {[...withDayNumbers].reverse().map((a) => {
            const scenario = scenarioMeta(a.scenario_type)
            const color = riskColor(a.risk_bucket)
            return (
              <tr key={a.created_at}>
                <td className="mono">Day {a._dayNumber}</td>
                <td className="mono">{formatDateTime(a.created_at)}</td>
                <td>
                  <span style={{ marginRight: 6 }}>{scenario.icon}</span>
                  {scenario.name}
                </td>
                {!severityIsStatic && (
                  <td className="mono">{a.severity !== null && a.severity !== undefined ? a.severity.toFixed(2) : '—'}</td>
                )}
                <td>
                  <span className="statusdot" style={{ background: color }} />
                  <span className="statuspill" style={{ color }}>
                    {a.risk_bucket}
                  </span>
                </td>
                <td className="mono">{a.nyha_class}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function TrendsHistoryPage({ patientId }) {
  const { history, wearableHistory, loading, error, reload } = useTrends(patientId)

  if (!patientId) {
    return (
      <div className="section">
        <div className="card statecard">
          <div className="statetitle">No patient selected</div>
          <div>Choose a patient from the sidebar to see their trends.</div>
        </div>
      </div>
    )
  }

  if (loading) return <DashboardSkeleton />
  if (error) return <ErrorState message={error} onRetry={reload} />

  const assessments = history?.assessments ?? []
  const readings = wearableHistory?.readings ?? []
  const patientLabel = avatarFromId(patientId).label

  const riskSeries = assessments.map((a) => ({ x: a.created_at, y: a.risk_score }))
  const latestColor = assessments.length ? riskColor(assessments[assessments.length - 1].risk_bucket) : '#14B8A6'

  return (
    <>
      <div className="topbar">
        <div>
          <div className="pagetitle">Trends & History</div>
          <div className="pagesub">{patientLabel} · risk trajectory and wearable history</div>
        </div>
      </div>

      <div className="section">
        <div className="sectitle">
          Risk Score Trend <span className="sub">across all completed assessments</span>
        </div>
        <div className="card" style={{ padding: '18px 20px' }}>
          {assessments.length > 0 ? (
            <TrendChart data={riskSeries} color={latestColor} formatX={SHORT_DATE} formatY={(v) => v.toFixed(2)} />
          ) : (
            <div className="trendchart-empty" style={{ height: 120 }}>
              No completed assessments yet
            </div>
          )}
        </div>
      </div>

      {assessments.length > 0 && (
        <div className="section">
          <div className="sectitle">
            Assessment History <span className="sub">{assessments.length} run{assessments.length === 1 ? '' : 's'}</span>
          </div>
          <RiskHistoryTable assessments={assessments} />
        </div>
      )}

      <div className="section">
        <div className="sectitle">
          Wearable Vitals <span className="sub">{readings.length}-day synced history</span>
        </div>
        {readings.length === 0 ? (
          <div className="card statecard">
            <div>No wearable readings synced yet.</div>
          </div>
        ) : (
          <div className="vitalsgrid">
            {VITAL_ORDER.map((key) => {
              const meta = vitalMeta(key)
              const series = readings.map((r) => ({ x: r.recorded_date, y: r[key] }))
              return (
                <div key={key} className="card vitalcard">
                  <div className="vitalcardhead">
                    <span>{meta.label}</span>
                    <span className="vitalcardunit">{meta.unit}</span>
                  </div>
                  <TrendChart data={series} color="#14B8A6" height={90} formatX={SHORT_DATE} formatY={(v) => fmt1(v)} />
                </div>
              )
            })}
          </div>
        )}
      </div>
    </>
  )
}
