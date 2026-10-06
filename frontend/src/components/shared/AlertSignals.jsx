// The two alert signals side by side (fix/alert-both-signals): the twin-based `alert` from
// decide_alert() (ALERT / WATCH / NONE, driven by the Pulse risk score) and the ML model's own
// severity signal (`ml_severity_alert`, severity above 0.15). Neither is folded into the other;
// when exactly one fires (`signals_disagree`) a plain note says which.

const LEVEL_COLOR = { ALERT: '#EF4444', WATCH: '#EAB308', NONE: '#22C55E' }

function disagreementNote(alert, ml) {
  if (!alert || !ml) return null
  if (alert.level === 'NONE') return "ML model flags this patient; the twin's risk score does not."
  return "The twin's risk score flags this patient; the ML model does not."
}

function SignalTag({ label, level, detail }) {
  const color = LEVEL_COLOR[level] ?? '#64748B'
  return (
    <span className="tag" style={{ color, borderColor: `${color}55` }} title={detail}>
      {label}: {level}
    </span>
  )
}

export default function AlertSignals({ alert, mlAlert, disagree }) {
  if (!alert && !mlAlert) return null
  const note = disagree ? disagreementNote(alert, mlAlert) : null
  return (
    <div style={{ marginTop: 8 }}>
      <div className="badgerow">
        {alert && <SignalTag label="Twin" level={alert.level} detail={`decide_alert() source: ${alert.source}`} />}
        {mlAlert && (
          <SignalTag
            label="ML severity"
            level={mlAlert.level}
            detail={`severity ${mlAlert.severity.toFixed(2)} vs threshold ${mlAlert.threshold}`}
          />
        )}
      </div>
      {note && (
        <div className="signalnote" style={{ marginTop: 6, fontSize: 12.5, fontWeight: 600, color: '#B45309' }}>
          {note}
        </div>
      )}
    </div>
  )
}
