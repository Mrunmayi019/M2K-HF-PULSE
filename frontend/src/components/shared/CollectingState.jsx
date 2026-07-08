const WEARABLE_WINDOW_DAYS = 21

export default function CollectingState({ readingCount }) {
  const pct = Math.min(100, Math.round((readingCount / WEARABLE_WINDOW_DAYS) * 100))
  return (
    <div className="section">
      <div className="card statecard">
        <div className="statetitle">Collecting wearable data</div>
        <div>
          {readingCount}/{WEARABLE_WINDOW_DAYS} days synced — the digital twin needs a full 21-day
          window before its first simulation runs.
        </div>
        <div className="probtrack" style={{ margin: '16px auto 0', maxWidth: 320 }}>
          <div className="probfill" style={{ width: `${pct}%`, background: 'var(--teal)' }} />
        </div>
      </div>
    </div>
  )
}
