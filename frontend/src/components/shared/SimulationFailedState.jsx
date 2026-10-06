import AlertSignals from './AlertSignals.jsx'

export default function SimulationFailedState({ errorMessage, onRetry, alert, mlAlert, disagree }) {
  return (
    <div className="section">
      <div className="card statecard" style={{ borderColor: 'rgba(239,68,68,.4)' }}>
        <div className="statetitle" style={{ color: 'var(--red)' }}>
          Simulation failed
        </div>
        <div>
          The last Pulse run for this patient didn't complete successfully. No risk assessment is
          shown below — showing stale or fabricated data here would be worse than showing nothing.
        </div>
        {/* With no twin physiology, `alert` falls back to the same ML-severity rule, so the two
            signals agree by construction here -- but the patient can still be flagged. */}
        <AlertSignals alert={alert} mlAlert={mlAlert} disagree={disagree} />
        {errorMessage && (
          <div className="mono" style={{ marginTop: 12, fontSize: 12, color: 'var(--muted)', textAlign: 'left', whiteSpace: 'pre-wrap' }}>
            {errorMessage}
          </div>
        )}
        {onRetry && (
          <button type="button" className="btn btn-ghost" onClick={onRetry}>
            Refresh status
          </button>
        )}
      </div>
    </div>
  )
}
