import { formatDateTime } from '../../utils/format.js'

export default function TopBar({ simTimeIso, isRefreshing, isCollecting, readingCount, onRunSimulation }) {
  return (
    <div className="topbar">
      <div>
        <div className="pagetitle">Patient Dashboard</div>
        <div className="pagesub">Heart failure digital twin · continuous monitoring</div>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div className="simtime">
          Last simulation: <b>{simTimeIso ? formatDateTime(simTimeIso) : 'never'}</b>
        </div>
        <button
          type="button"
          className="btn btn-primary"
          onClick={onRunSimulation}
          disabled={isRefreshing || isCollecting}
          title={isCollecting ? `${readingCount}/21 days collected` : undefined}
        >
          {isRefreshing && <span className="spin" />}
          {isRefreshing ? 'Refreshing…' : isCollecting ? `${readingCount}/21 days collected` : 'Run New Simulation'}
        </button>
      </div>
    </div>
  )
}
