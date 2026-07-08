// Network/backend-unreachable error -- distinct from a *failed simulation* (SimulationFailedState),
// which is a successful API response reporting simulation_status === "failed".
export default function ErrorState({ message, onRetry }) {
  return (
    <div className="section">
      <div className="card statecard">
        <div className="statetitle">Couldn't reach the backend</div>
        <div>{message || 'Check that the API server is running and VITE_API_URL is correct.'}</div>
        {onRetry && (
          <button type="button" className="btn btn-ghost" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  )
}
