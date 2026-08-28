import { useState } from 'react'
import Sidebar from './Sidebar.jsx'
import TopBar from './TopBar.jsx'
import HeroStatusCard from '../hero/HeroStatusCard.jsx'
import CurrentConditionPanel from '../condition/CurrentConditionPanel.jsx'
import VitalsTable from '../vitals/VitalsTable.jsx'
import ForwardProjectionPanel from '../projection/ForwardProjectionPanel.jsx'
import CardiacWaveformPanel from '../waveform/CardiacWaveformPanel.jsx'
import DoctorReportCard from '../report/DoctorReportCard.jsx'
import { DashboardSkeleton } from '../shared/Skeleton.jsx'
import ErrorState from '../shared/ErrorState.jsx'
import CollectingState from '../shared/CollectingState.jsx'
import SimulationFailedState from '../shared/SimulationFailedState.jsx'
import SimulationRunningBanner from '../shared/SimulationRunningBanner.jsx'
import TrendsHistoryPage from '../trends/TrendsHistoryPage.jsx'
import SimulationLabPage from '../lab/SimulationLabPage.jsx'
import ReportsPage from '../reports/ReportsPage.jsx'
import SettingsPage from '../settings/SettingsPage.jsx'
import { usePatients } from '../../hooks/usePatients.js'
import { usePatientReport } from '../../hooks/usePatientReport.js'
import { useTheme } from '../../hooks/useTheme.js'
import { avatarFromId } from '../../utils/format.js'

function DashboardBody({ patientId, patient }) {
  const { report, loading, refreshing, error, refresh } = usePatientReport(patientId)

  if (loading) return <DashboardSkeleton />
  if (error) return <ErrorState message={error} onRetry={refresh} />

  const status = report.status
  const simStatus = status.simulation_status
  const assessment = status.latest_assessment
  const wearable = status.latest_wearable
  const patientLabel = avatarFromId(patientId).label

  // NOTE: routes.py's _build_status reports "complete" whenever *any* prior assessment exists,
  // even if a newer run is currently in progress -- so "running"/"pending" is only actually
  // observable before a patient's very first assessment completes. Built correctly for both,
  // not worked around, since changing that branching is out of scope for this frontend task.
  if (simStatus === 'collecting') {
    return (
      <>
        <TopBar simTimeIso={null} isRefreshing={refreshing} isCollecting readingCount={status.reading_count} onRunSimulation={refresh} />
        <CollectingState readingCount={status.reading_count} />
      </>
    )
  }

  if ((simStatus === 'running' || simStatus === 'pending') && !assessment) {
    return (
      <>
        <TopBar simTimeIso={null} isRefreshing={refreshing} isCollecting={false} readingCount={status.reading_count} onRunSimulation={refresh} />
        <div className="section">
          <div className="card statecard">
            <div className="statetitle">Simulation running</div>
            <div>The first assessment for this patient is being computed — this can take a few minutes.</div>
          </div>
        </div>
      </>
    )
  }

  if (simStatus === 'failed') {
    return (
      <>
        <TopBar simTimeIso={assessment?.created_at} isRefreshing={refreshing} isCollecting={false} readingCount={status.reading_count} onRunSimulation={refresh} />
        <SimulationFailedState errorMessage={status.error_message} onRetry={refresh} />
      </>
    )
  }

  return (
    <>
      <TopBar simTimeIso={assessment?.created_at} isRefreshing={refreshing} isCollecting={false} readingCount={status.reading_count} onRunSimulation={refresh} />
      {(simStatus === 'running' || simStatus === 'pending') && <SimulationRunningBanner />}
      <HeroStatusCard assessment={assessment} patientLabel={patientLabel} />
      <CurrentConditionPanel assessment={assessment} wearable={wearable} />
      <VitalsTable wearable={wearable} vitalSlopes={assessment?.vital_slopes} />
      <CardiacWaveformPanel waveformData={status.waveform_data} assessment={assessment} />
      <ForwardProjectionPanel assessment={assessment} horizons={report.projection?.horizons} />
      <DoctorReportCard
        patientLabel={patientLabel}
        patient={patient}
        assessment={assessment}
        wearable={wearable}
        waveformData={status.waveform_data}
      />
    </>
  )
}

export default function AppShell() {
  const { patients, reports, error: patientsError, reload } = usePatients()
  const [selectedId, setSelectedId] = useState(null)
  const [activeTab, setActiveTab] = useState('dashboard')
  const { theme, setTheme } = useTheme()

  const activeId = selectedId ?? patients?.[0]?.id ?? null

  function handlePatientCreated(patientId) {
    reload()
    setSelectedId(patientId)
  }

  return (
    <div className="app">
      <Sidebar
        patients={patients}
        reports={reports}
        selectedId={activeId}
        onSelect={setSelectedId}
        activeTab={activeTab}
        onNavigate={setActiveTab}
      />
      <div className="main">
        {patientsError && <ErrorState message={patientsError} onRetry={reload} />}

        {!patientsError && activeTab === 'dashboard' && (
          <>
            {patients?.length === 0 && (
              <div className="section">
                <div className="card statecard">
                  <div className="statetitle">No patients yet</div>
                  <div>Create one in the Simulation Lab to start monitoring.</div>
                  <button type="button" className="btn btn-teal" onClick={() => setActiveTab('lab')}>
                    Go to Simulation Lab
                  </button>
                </div>
              </div>
            )}
            {activeId && <DashboardBody patientId={activeId} patient={patients?.find((p) => p.id === activeId)} />}
          </>
        )}

        {!patientsError && activeTab === 'trends' && <TrendsHistoryPage patientId={activeId} />}

        {!patientsError && activeTab === 'lab' && (
          <SimulationLabPage selectedPatientId={activeId} onPatientCreated={handlePatientCreated} />
        )}

        {!patientsError && activeTab === 'reports' && (
          <ReportsPage patients={patients} reports={reports} selectedId={activeId} onSelect={setSelectedId} />
        )}

        {!patientsError && activeTab === 'settings' && <SettingsPage theme={theme} setTheme={setTheme} />}
      </div>
    </div>
  )
}
