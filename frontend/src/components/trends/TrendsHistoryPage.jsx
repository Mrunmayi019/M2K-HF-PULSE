import TrendChart from './TrendChart.jsx'
import { DashboardSkeleton } from '../shared/Skeleton.jsx'
import ErrorState from '../shared/ErrorState.jsx'
import { useTrends } from '../../hooks/useTrends.js'
import { VITAL_ORDER, vitalMeta, fmt1, riskColor, scenarioMeta, formatDateTime, avatarFromId } from '../../utils/format.js'

const SHORT_DATE = (iso) => new Date(iso).toLocaleDateString([], { month: 'short', day: 'numeric' })

function RiskHistoryTable({ assessments }) {
  return (
    <div className="card tablewrap">
      <table className="vt">
        <thead>
          <tr>
            <th>Date</th>
            <th>Scenario</th>
            <th>Severity</th>
            <th>Risk</th>
            <th>NYHA</th>
          </tr>
        </thead>
        <tbody>
          {[...assessments].reverse().map((a) => {
            const scenario = scenarioMeta(a.scenario_type)
            const color = riskColor(a.risk_bucket)
            return (
              <tr key={a.created_at}>
                <td className="mono">{formatDateTime(a.created_at)}</td>
                <td>
                  <span style={{ marginRight: 6 }}>{scenario.icon}</span>
                  {scenario.name}
                </td>
                <td className="mono">{a.severity !== null && a.severity !== undefined ? a.severity.toFixed(2) : '—'}</td>
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
