import { VITAL_ORDER, vitalMeta, vitalStatus, trendDirection, fmt1 } from '../../utils/format.js'

export default function VitalsTable({ wearable, vitalSlopes }) {
  return (
    <div className="section">
      <div className="sectitle">
        Vitals <span className="sub">latest wearable sync vs. 21-day trend</span>
      </div>
      <div className="card tablewrap">
        <table className="vt">
          <thead>
            <tr>
              <th>Metric</th>
              <th>Today's Input</th>
              <th>7-Day Trend</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {VITAL_ORDER.map((key) => {
              const meta = vitalMeta(key)
              const value = wearable?.[key]
              const slope = vitalSlopes?.[key]
              const { arrow, worsening } = trendDirection(key, slope)
              const status = wearable ? vitalStatus(key, value) : null
              return (
                <tr key={key}>
                  <td className="rowlabel">{meta.label}</td>
                  <td className="mono">{value === undefined || value === null ? '—' : `${fmt1(value)} ${meta.unit}`}</td>
                  <td className="mono" style={{ color: slope === undefined || slope === null ? 'inherit' : worsening ? '#EF4444' : '#22C55E' }}>
                    {slope === undefined || slope === null ? '—' : `${arrow} ${fmt1(Math.abs(slope))} ${meta.unit}/day`}
                  </td>
                  <td>
                    {status && (
                      <>
                        <span className="statusdot" style={{ background: status === 'Attention' ? '#EAB308' : '#22C55E' }} />
                        <span className="statuspill" style={{ color: status === 'Attention' ? '#B45309' : '#15803D' }}>
                          {status}
                        </span>
                      </>
                    )}
                    {!status && '—'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
