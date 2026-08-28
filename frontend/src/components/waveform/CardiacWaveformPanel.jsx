import { useMemo } from 'react'
import TrendChart from '../trends/TrendChart.jsx'
import PVLoopChart from './PVLoopChart.jsx'
import { fmt1 } from '../../utils/format.js'

// Derived, not fabricated: every number here is a min/max/arithmetic read off the same
// waveform_data the charts plot -- no separate clinical formula, no new citation needed.
// See docs/methodology.md's Known Engine Constraints section for why nothing about *interpreting*
// loop shape (e.g. "this shape indicates diastolic dysfunction") is claimed here -- this project's
// standing rule is no unvalidated clinical inference, and loop-morphology classification was never
// validated against real echocardiographic data.
function deriveStats(waveformData) {
  const loop = waveformData?.pv_loop ?? []
  if (loop.length < 2) return null
  const vols = loop.map((p) => p.volume_ml)
  const press = loop.map((p) => p.pressure_mmhg)
  const strokeVolumeMl = Math.max(...vols) - Math.min(...vols)
  const pulsePressureMmhg = Math.max(...press) - Math.min(...press)
  const impliedHr = waveformData.cycle_duration_s ? 60 / waveformData.cycle_duration_s : null
  return { strokeVolumeMl, pulsePressureMmhg, impliedHr }
}

export default function CardiacWaveformPanel({ waveformData, assessment }) {
  const stats = useMemo(() => deriveStats(waveformData), [waveformData])
  const ecgPoints = useMemo(
    () => (waveformData?.ecg ?? []).map((p) => ({ x: p.t_s, y: p.mv })),
    [waveformData],
  )

  if (!waveformData) {
    return (
      <div className="section">
        <div className="sectitle">
          Cardiac Waveform <span className="sub">ECG trace &amp; pressure-volume loop, from this run's Pulse simulation</span>
        </div>
        <div className="card statecard">
          <div className="statetitle">Not available for this assessment</div>
          <div>Waveform data is captured on new simulation runs — run a fresh simulation to see it here.</div>
        </div>
      </div>
    )
  }

  return (
    <div className="section">
      <div className="sectitle">
        Cardiac Waveform <span className="sub">ECG trace &amp; pressure-volume loop, from this run's Pulse simulation</span>
      </div>
      <div className="grid2">
        <div className="card waveformcard">
          <div className="waveformcardtitle">ECG (Lead III, simulated)</div>
          <TrendChart data={ecgPoints} color="#F472B6" unit=" mV" height={140} formatX={(v) => `${v.toFixed(2)}s`} formatY={(v) => v.toFixed(3)} />
        </div>
        <div className="card waveformcard">
          <div className="waveformcardtitle">Pressure-Volume Loop (left heart, one cycle)</div>
          <PVLoopChart points={waveformData.pv_loop} height={140} />
        </div>
      </div>
      {stats && (
        <div className="card waveformstats">
          <div className="minicard">
            <div className="minival">{fmt1(stats.strokeVolumeMl)}</div>
            <div className="minilabel">Stroke Volume (mL, from loop)</div>
          </div>
          <div className="minicard">
            <div className="minival">{fmt1(stats.pulsePressureMmhg)}</div>
            <div className="minilabel">Pulse Pressure (mmHg, from loop)</div>
          </div>
          <div className="minicard">
            <div className="minival">{stats.impliedHr ? Math.round(stats.impliedHr) : '—'}</div>
            <div className="minilabel">Implied HR (bpm, from ECG cycle)</div>
          </div>
        </div>
      )}
      {assessment?.severity != null && (
        <div className="footnote">
          Cross-check: this loop's stroke volume ({stats ? fmt1(stats.strokeVolumeMl) : '—'} mL) and the
          simulation's independently-tracked stroke volume signal (used in the risk score's compensation
          flag) come from two different Pulse output properties measuring the same underlying
          quantity — close agreement between them is evidence the simulation is internally consistent,
          not a claim about this patient's real cardiac function.
        </div>
      )}
    </div>
  )
}
