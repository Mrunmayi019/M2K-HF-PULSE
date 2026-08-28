import { useState } from 'react'
import { createPatient, createClinicalReport, syncWearableReading } from '../../api/client.js'
import { generateTrend, TREND_PRESETS } from '../../utils/syntheticTrend.js'
import { usePatientReport } from '../../hooks/usePatientReport.js'
import { scenarioMeta, riskColor, avatarFromId, fmt1 } from '../../utils/format.js'

const COMPONENT_LABELS = {
  hr_rise: 'Heart Rate Rise',
  map_drop: 'MAP Drop',
  co_drop_pct: 'Cardiac Output Drop',
  compensation_flag: 'Compensation Flag',
  instability_flag: 'Instability Flag',
}

const emptyStartEnd = () => ({
  start: { hr: 72, spo2: 97, weightDelta: 0, steps: 7500, sleep: 7.0, hrv: 32 },
  end: { hr: 73, spo2: 97, weightDelta: 0.1, steps: 7300, sleep: 6.9, hrv: 31 },
})

function NumberField({ label, unit, value, onChange, min, max, step = 'any' }) {
  return (
    <label className="field">
      <span className="fieldlabel">{label}</span>
      <div className="fieldinputwrap">
        <input
          className="input"
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
        />
        {unit && <span className="fieldunit">{unit}</span>}
      </div>
    </label>
  )
}

function TrendPointFields({ title, point, onChange }) {
  return (
    <div className="trendpointcol">
      <div className="trendpointtitle">{title}</div>
      <div className="fieldgrid3">
        <NumberField label="Heart Rate" unit="bpm" value={point.hr} onChange={(v) => onChange({ ...point, hr: v })} min={20} max={220} />
        <NumberField label="SpO2" unit="%" value={point.spo2} onChange={(v) => onChange({ ...point, spo2: v })} min={50} max={100} />
        <NumberField label="Weight Δ" unit="kg" value={point.weightDelta} onChange={(v) => onChange({ ...point, weightDelta: v })} min={-20} max={20} />
        <NumberField label="Steps/day" unit="" value={point.steps} onChange={(v) => onChange({ ...point, steps: v })} min={0} max={30000} step={100} />
        <NumberField label="Sleep" unit="hrs" value={point.sleep} onChange={(v) => onChange({ ...point, sleep: v })} min={0} max={14} />
        <NumberField label="HRV (RMSSD)" unit="ms" value={point.hrv} onChange={(v) => onChange({ ...point, hrv: v })} min={0} max={150} />
      </div>
    </div>
  )
}

function NewPatientWizard({ onCreated }) {
  const [age, setAge] = useState(68)
  const [sex, setSex] = useState('Male')
  const [heightCm, setHeightCm] = useState(172)
  const [weightKg, setWeightKg] = useState(82)
  const [ef, setEf] = useState('')
  const [bnp, setBnp] = useState('')
  const [trend, setTrend] = useState(emptyStartEnd())
  const [preset, setPreset] = useState('stable')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(null)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)

  function applyPreset(key) {
    setPreset(key)
    const p = TREND_PRESETS[key]
    setTrend({ start: { ...p.start }, end: { ...p.end } })
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      setProgress('Creating patient…')
      const patient = await createPatient({ age: Number(age), sex, height_cm: Number(heightCm), weight_kg: Number(weightKg) })

      setProgress('Submitting clinical report…')
      await createClinicalReport(patient.id, {
        ejection_fraction_pct: ef === '' ? null : Number(ef),
        nt_probnp_pg_ml: bnp === '' ? null : Number(bnp),
      })

      const readings = generateTrend({ start: trend.start, end: trend.end, weightKg: Number(weightKg) })
      let lastStatus = null
      for (let i = 0; i < readings.length; i++) {
        setProgress(`Syncing wearable day ${i + 1}/${readings.length}…`)
        // eslint-disable-next-line no-await-in-loop
        lastStatus = await syncWearableReading(patient.id, readings[i])
      }

      setProgress(null)
      setResult({ patient, status: lastStatus })
      onCreated?.(patient.id)
    } catch (err) {
      setError(err.message)
      setProgress(null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card labform" onSubmit={handleSubmit}>
      <div className="labformsection">
        <div className="labformtitle">1. Demographics</div>
        <div className="fieldgrid4">
          <NumberField label="Age" unit="yrs" value={age} onChange={setAge} min={0} max={120} />
          <label className="field">
            <span className="fieldlabel">Sex</span>
            <select className="input select" value={sex} onChange={(e) => setSex(e.target.value)}>
              <option value="Male">Male</option>
              <option value="Female">Female</option>
            </select>
          </label>
          <NumberField label="Height" unit="cm" value={heightCm} onChange={setHeightCm} min={50} max={250} />
          <NumberField label="Weight" unit="kg" value={weightKg} onChange={setWeightKg} min={2} max={400} />
        </div>
      </div>

      <div className="labformsection">
        <div className="labformtitle">
          2. Clinical Report <span className="sub">optional — Tier-1 fallback applies if left blank</span>
        </div>
        <div className="fieldgrid4">
          <NumberField label="Ejection Fraction" unit="%" value={ef} onChange={setEf} min={0} max={100} />
          <NumberField label="NT-proBNP" unit="pg/mL" value={bnp} onChange={setBnp} min={0} max={50000} step={1} />
        </div>
      </div>

      <div className="labformsection">
        <div className="labformtitle">
          3. 21-Day Wearable Trend <span className="sub">synthetic — interpolated from start → end, with daily noise</span>
        </div>
        <div className="presetbtns">
          {Object.entries(TREND_PRESETS).map(([key, p]) => (
            <button key={key} type="button" className={`presetbtn ${preset === key ? 'active' : ''}`} onClick={() => applyPreset(key)}>
              {p.label}
            </button>
          ))}
        </div>
        <div className="trendpointgrid">
          <TrendPointFields title="Day 1 (start)" point={trend.start} onChange={(p) => { setPreset(null); setTrend((t) => ({ ...t, start: p })) }} />
          <TrendPointFields title="Day 21 (today)" point={trend.end} onChange={(p) => { setPreset(null); setTrend((t) => ({ ...t, end: p })) }} />
        </div>
      </div>

      {error && <div className="labformerror">{error}</div>}

      <div className="labformfooter">
        {progress && (
          <div className="labprogress">
            <span className="spin spin-dark" /> {progress}
          </div>
        )}
        {result && !busy && (
          <div className="labresult">
            Patient created — {result.status.message}
          </div>
        )}
        <button type="submit" className="btn btn-teal" disabled={busy}>
          {busy ? 'Running…' : 'Create Patient & Start Monitoring'}
        </button>
      </div>
    </form>
  )
}

function ComponentMeter({ label, value }) {
  const pct = Math.round(Math.max(0, Math.min(1, value ?? 0)) * 100)
  return (
    <div className="metercard">
      <div className="meterhead">
        <span>{label}</span>
        <span className="mono">{fmt1(value ?? 0)}</span>
      </div>
      <div className="probtrack">
        <div className="probfill" style={{ width: `${pct}%`, background: pct > 50 ? '#EF4444' : pct > 20 ? '#EAB308' : '#14B8A6' }} />
      </div>
    </div>
  )
}

function SimulationInternals({ patientId }) {
  const { report, loading } = usePatientReport(patientId)

  if (!patientId) return null
  if (loading || !report) return null

  const assessment = report.status.latest_assessment
  const patientLabel = avatarFromId(patientId).label

  if (!assessment) {
    return (
      <div className="card statecard">
        <div className="statetitle">No completed simulation yet for {patientLabel}</div>
        <div>Component-score breakdown appears here once the pipeline finishes.</div>
      </div>
    )
  }

  const scenario = scenarioMeta(assessment.scenario_type)
  const color = riskColor(assessment.risk_bucket)

  return (
    <div className="card" style={{ padding: 24 }}>
      <div className="scenariorow">
        <div className="scenicon" style={{ background: `${scenario.color}1A`, color: scenario.color }}>
          {scenario.icon}
        </div>
        <div>
          <div className="scenname">{scenario.name}</div>
          <div className="scensub">
            {patientLabel} · severity {assessment.severity?.toFixed(2)} · risk score {assessment.risk_score?.toFixed(3)}
          </div>
        </div>
        <div className="riskbadge" style={{ marginLeft: 'auto', background: `${color}1A`, color }}>
          {assessment.risk_bucket} RISK
        </div>
      </div>
      {assessment.dominant_mechanism === 'baseline' && (
        <div className="mechanismnote">
          This score is driven by <b>chronic baseline congestion</b> (this patient's resting MAP
          is already low, not an acute change during the simulated encounter) — the 5 meters
          below measure only <i>acute</i> change during the run and correctly read near-zero here.
          Baseline deficit score: <b>{assessment.baseline_deficit_score?.toFixed(3)}</b> (this is
          what actually produced the {assessment.risk_score?.toFixed(3)} above).
        </div>
      )}
      <div className="metergrid">
        {Object.entries(assessment.component_scores ?? {}).map(([key, value]) => (
          <ComponentMeter key={key} label={COMPONENT_LABELS[key] ?? key} value={value} />
        ))}
      </div>
    </div>
  )
}

export default function SimulationLabPage({ selectedPatientId, onPatientCreated }) {
  return (
    <>
      <div className="topbar">
        <div>
          <div className="pagetitle">Simulation Lab</div>
          <div className="pagesub">Create synthetic patients and inspect raw Pulse simulation output</div>
        </div>
      </div>

      <div className="section">
        <div className="sectitle">
          New Simulation <span className="sub">runs the full pipeline: ML classification → Pulse → risk scoring → staging</span>
        </div>
        <NewPatientWizard onCreated={onPatientCreated} />
      </div>

      <div className="section">
        <div className="sectitle">
          Simulation Internals <span className="sub">component-score breakdown for the selected patient</span>
        </div>
        <SimulationInternals patientId={selectedPatientId} />
      </div>
    </>
  )
}
