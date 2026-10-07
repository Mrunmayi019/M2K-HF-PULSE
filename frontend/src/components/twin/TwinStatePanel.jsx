import { useCallback, useEffect, useState } from 'react'
import { getTwinState, resetTwinState } from '../../api/client.js'
import { isDefaultFlags } from '../../utils/twinState.js'

// feature/wire-research-features. Shows the research feature flags and, in continuous mode, the
// state of the carried-forward Pulse twin, with a manual reset. Renders nothing when every flag is
// at its default (fresh mode, all features off), so the default dashboard is unchanged.

function fmtDate(iso) {
  if (!iso) return '—'
  // The API returns naive UTC timestamps (SQLite); mark them as UTC before formatting locally.
  return new Date(/[Zz]|[+-]\d\d:\d\d$/.test(iso) ? iso : `${iso}Z`).toLocaleString()
}

function Stat({ label, value, warn }) {
  return (
    <div style={{ minWidth: 150 }}>
      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: warn ? 'var(--red)' : 'var(--text)' }}>{value}</div>
    </div>
  )
}

function personalisationText(pers) {
  const parts = []
  if (pers.bcg) {
    parts.push(`BCG modifiers ${pers.bcg.applied ? 'applied' : 'not applied'}${pers.bcg.note ? ` (${pers.bcg.note})` : ''}.`)
  }
  if (pers.hr_baseline) {
    const h = pers.hr_baseline
    parts.push(
      `HR baseline ${h.requested_bpm} bpm, simulated at ${h.simulated_bpm}${h.applied ? '' : ', not applied'}${h.note ? ` (${h.note})` : ''}.`,
    )
  }
  return parts.join(' ')
}

export default function TwinStatePanel({ patientId, assessment, refreshKey, onReset }) {
  const [twin, setTwin] = useState(null)
  const [error, setError] = useState(null)
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    try {
      setTwin(await getTwinState(patientId))
      setError(null)
    } catch (err) {
      setError(err.message)
    }
  }, [patientId])

  useEffect(() => {
    setTwin(null)
    setConfirming(false)
    load()
  }, [load, refreshKey])

  if (!twin || isDefaultFlags(twin.flags)) return null

  const continuous = twin.pipeline_mode === 'continuous'
  const onFlags = Object.entries(twin.flags)
    .filter(([k, v]) => k !== 'PIPELINE_MODE' && v === true)
    .map(([k]) => k)
  const pers = assessment?.personalisation

  async function doReset() {
    setBusy(true)
    try {
      await resetTwinState(patientId)
      setConfirming(false)
      await load()
      onReset?.()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="section">
      <div className="sectitle">
        Twin State <span className="sub">research feature flags</span>
      </div>
      <div className="card" style={{ padding: '16px 20px', display: 'grid', gap: 14 }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 20 }}>
          <Stat label="Pipeline mode" value={continuous ? 'Continuous (state carried forward)' : 'Fresh (rebuilt every run)'} />
          {continuous && (
            <>
              <Stat
                label="Current state started"
                value={twin.reset_pending ? 'Reset: fresh start on next run' : fmtDate(twin.state_started_at)}
              />
              <Stat label="Days in this state" value={twin.state_days} />
              <Stat label="engine_lag_days" value={twin.engine_lag_days} warn={twin.engine_lag_days > 0} />
              <Stat
                label="Days since Exercise-triggering label"
                value={
                  twin.days_since_exercise_label === null
                    ? 'none in this state'
                    : `${twin.days_since_exercise_label} (${twin.last_exercise_scenario_type})`
                }
              />
            </>
          )}
        </div>

        {continuous && twin.hfref_condition_mismatch && (
          <div style={{ fontSize: 13, color: 'var(--red)' }}>
            The latest EF is on the other side of the 40% cutoff from the EF this state started with. The
            chronic-dysfunction condition is only set when a state starts, so the twin can&apos;t follow this
            change until it is reset.
          </div>
        )}

        {onFlags.length > 0 && (
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>Experimental flags on: {onFlags.join(', ')}</div>
        )}

        {pers && (
          <div style={{ fontSize: 12, color: 'var(--muted)' }}>
            Latest run personalisation: {personalisationText(pers)} Experimental: calibrated on 2 subjects from one
            dataset; BCG amplitude units are specific to that dataset.
          </div>
        )}

        {error && <div style={{ fontSize: 12, color: 'var(--red)' }}>{error}</div>}

        {continuous && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            {!confirming ? (
              <button type="button" className="btn btn-ghost" onClick={() => setConfirming(true)} disabled={twin.reset_pending}>
                Reset twin state
              </button>
            ) : (
              <>
                <span style={{ fontSize: 13 }}>Start a fresh twin from the next run? History is kept.</span>
                <button type="button" className="btn btn-primary" onClick={doReset} disabled={busy}>
                  {busy ? 'Resetting…' : 'Confirm reset'}
                </button>
                <button type="button" className="btn btn-ghost" onClick={() => setConfirming(false)} disabled={busy}>
                  Cancel
                </button>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
