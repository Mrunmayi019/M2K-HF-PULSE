import { useState } from 'react'
import DoctorReportCard from '../report/DoctorReportCard.jsx'
import { avatarFromId, riskColor, scenarioMeta } from '../../utils/format.js'

function ReportRow({ patient, report, selected, onSelect }) {
  const avatar = avatarFromId(patient.id)
  const assessment = report?.status?.latest_assessment
  const simStatus = report?.status?.simulation_status
  const scenario = assessment ? scenarioMeta(assessment.scenario_type) : null
  const color = assessment ? riskColor(assessment.risk_bucket) : '#64748B'

  return (
    <div className={`reportrow ${selected ? 'sel' : ''}`} onClick={() => onSelect(patient.id)}>
      <div className="pavatar" style={{ background: avatar.color }}>
        {avatar.initials}
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="pname" style={{ color: 'var(--navy)' }}>
          {avatar.label}
        </div>
        <div className="pmeta" style={{ color: 'var(--muted)' }}>
          {patient.age} yrs · {patient.sex} {scenario ? `· ${scenario.name}` : ''}
        </div>
      </div>
      {assessment ? (
        <span className="statuspill" style={{ color }}>
          <span className="statusdot" style={{ background: color }} />
          {assessment.risk_bucket}
        </span>
      ) : (
        <span className="pmeta" style={{ color: 'var(--muted)' }}>
          {simStatus === 'collecting' ? 'collecting' : simStatus ?? 'pending'}
        </span>
      )}
    </div>
  )
}

export default function ReportsPage({ patients, reports, selectedId, onSelect }) {
  const [activeId, setActiveId] = useState(selectedId)
  const active = patients?.find((p) => p.id === activeId) ?? patients?.[0]
  const activeReport = active ? reports?.[active.id] : null

  function handleSelect(id) {
    setActiveId(id)
    onSelect?.(id)
  }

  if (!patients || patients.length === 0) {
    return (
      <>
        <div className="topbar">
          <div>
            <div className="pagetitle">Reports</div>
            <div className="pagesub">Clinical summary reports across all patients</div>
          </div>
        </div>
        <div className="card statecard">
          <div className="statetitle">No patients yet</div>
          <div>Create one in the Simulation Lab to generate a report.</div>
        </div>
      </>
    )
  }

  const activeLabel = active ? avatarFromId(active.id).label : ''

  return (
    <>
      <div className="topbar">
        <div>
          <div className="pagetitle">Reports</div>
          <div className="pagesub">Clinical summary reports across all patients</div>
        </div>
      </div>
      <div className="grid2">
        <div className="section" style={{ marginBottom: 0 }}>
          <div className="sectitle">
            All Patients <span className="sub">{patients.length}</span>
          </div>
          <div className="card reportslist">
            {patients.map((p) => (
              <ReportRow key={p.id} patient={p} report={reports?.[p.id]} selected={p.id === active?.id} onSelect={handleSelect} />
            ))}
          </div>
        </div>
        <div>
          <div className="sectitle">
            Report Preview <span className="sub">{activeLabel}</span>
          </div>
          <DoctorReportCard
            patientLabel={activeLabel}
            patient={active}
            assessment={activeReport?.status?.latest_assessment}
            wearable={activeReport?.status?.latest_wearable}
          />
        </div>
      </div>
    </>
  )
}
