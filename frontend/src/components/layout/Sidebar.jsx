import { useMemo, useState } from 'react'
import { avatarFromId } from '../../utils/format.js'

export const NAV_ITEMS = [
  { key: 'dashboard', label: 'Patient Dashboard' },
  { key: 'trends', label: 'Trends & History' },
  { key: 'lab', label: 'Simulation Lab' },
  { key: 'reports', label: 'Reports' },
  { key: 'settings', label: 'Settings' },
]

function patientMeta(patient, report) {
  const bucket = report?.status?.latest_assessment?.risk_bucket
  const status = report?.status?.simulation_status
  const riskLabel = bucket ? `${bucket.charAt(0)}${bucket.slice(1).toLowerCase()} risk` : status === 'collecting' ? 'collecting data' : 'pending'
  return `${patient.age} yrs · ${riskLabel}`
}

export default function Sidebar({ patients, reports, selectedId, onSelect, activeTab, onNavigate }) {
  const [query, setQuery] = useState('')

  // Matches against the full UUID (so a pasted ID always works) and the displayed "#XXXX" label
  // (so a user can type what they actually see on screen) -- patient rows have no real name to
  // search by otherwise. Case-insensitive, dashes stripped so "1a8f" and "1A8F8EA9-..." both hit.
  const filtered = useMemo(() => {
    if (!patients) return patients
    const q = query.trim().toLowerCase().replace(/-/g, '')
    if (!q) return patients
    return patients.filter((p) => p.id.replace(/-/g, '').toLowerCase().includes(q))
  }, [patients, query])

  return (
    <div className="sidebar">
      <div className="brand">
        <div className="brandmark">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M3 12h4l2-6 4 12 2-6h6" stroke="white" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div>
          <div className="brandname">HeartGuard AI</div>
          <div className="brandsub">Digital Twin Platform</div>
        </div>
      </div>
      <div>
        <div className="navsec">Menu</div>
        {NAV_ITEMS.map((item) => (
          <div
            key={item.key}
            className={`navitem ${item.key === activeTab ? 'active' : ''}`}
            onClick={() => onNavigate(item.key)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && onNavigate(item.key)}
          >
            <span className="navdot" />
            {item.label}
          </div>
        ))}
      </div>
      <div className="patientcard">
        <div className="plabel">Patients</div>
        {patients?.length > 0 && (
          <input
            className="patientsearch"
            type="text"
            placeholder="Search by ID or #XXXX…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        )}
        {patients === null && <div className="pmeta">Loading…</div>}
        {patients?.length === 0 && <div className="pmeta">No patients yet.</div>}
        {patients?.length > 0 && filtered.length === 0 && <div className="pmeta">No patients match "{query}".</div>}
        {filtered?.map((p) => {
          const avatar = avatarFromId(p.id)
          return (
            <div key={p.id} className={`prow ${p.id === selectedId ? 'sel' : ''}`} onClick={() => onSelect(p.id)}>
              <div className="pavatar" style={{ background: avatar.color }}>
                {avatar.initials}
              </div>
              <div>
                <div className="pname">{avatar.label}</div>
                <div className="pmeta">{patientMeta(p, reports?.[p.id])}</div>
              </div>
            </div>
          )
        })}
      </div>
      <div style={{ marginTop: 'auto', fontSize: 10.5, color: '#64748B' }}>v0.1.0 · HIPAA-audited env</div>
    </div>
  )
}
