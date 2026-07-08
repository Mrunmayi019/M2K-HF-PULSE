// Shown above a *stale but present* previous assessment while a new run is in progress --
// keeps the last-known state visible (dimmed) instead of hiding everything mid-simulation.
export default function SimulationRunningBanner() {
  return (
    <div className="runningbanner">
      <span className="spin spin-dark" />
      Simulation in progress — the numbers below are from the last completed run.
    </div>
  )
}
