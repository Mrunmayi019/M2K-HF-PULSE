import { useState } from 'react'
import { listPatients, BASE_URL } from '../../api/client.js'

const THEME_OPTIONS = [
  { key: 'system', label: 'System' },
  { key: 'light', label: 'Light' },
  { key: 'dark', label: 'Dark' },
]

function ConnectionCheck() {
  const [state, setState] = useState(null) // { ok, ms, error }
  const [checking, setChecking] = useState(false)

  async function check() {
    setChecking(true)
    const started = performance.now()
    try {
      await listPatients()
      setState({ ok: true, ms: Math.round(performance.now() - started) })
    } catch (err) {
      setState({ ok: false, error: err.message })
    } finally {
      setChecking(false)
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, alignItems: 'flex-end' }}>
      <button type="button" className="btn btn-ghost" onClick={check} disabled={checking}>
        {checking && <span className="spin spin-dark" />}
        {checking ? 'Checking…' : 'Test Connection'}
      </button>
      {state && (
        <div className="conncheck">
          <span className="conndot" style={{ background: state.ok ? '#22C55E' : '#EF4444' }} />
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>
            {state.ok ? `Connected · ${state.ms}ms` : state.error}
          </span>
        </div>
      )}
    </div>
  )
}

export default function SettingsPage({ theme, setTheme }) {
  return (
    <>
      <div className="topbar">
        <div>
          <div className="pagetitle">Settings</div>
          <div className="pagesub">Platform preferences and connection status</div>
        </div>
      </div>

      <div className="section">
        <div className="sectitle">Appearance</div>
        <div className="card settingscard">
          <div className="settingsrow">
            <div>
              <div className="settingslabel">Theme</div>
              <div className="settingsdesc">Follows your OS setting by default, or pin it to light/dark.</div>
            </div>
            <div className="themebtns">
              {THEME_OPTIONS.map((opt) => (
                <button
                  key={opt.key}
                  type="button"
                  className={`themebtn ${theme === opt.key ? 'active' : ''}`}
                  onClick={() => setTheme(opt.key)}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="section">
        <div className="sectitle">API Connection</div>
        <div className="card settingscard">
          <div className="settingsrow">
            <div>
              <div className="settingslabel">Backend URL</div>
              <div className="settingsdesc mono">{BASE_URL}</div>
            </div>
            <ConnectionCheck />
          </div>
          <div className="settingsrow">
            <div>
              <div className="settingslabel">Interactive API docs</div>
              <div className="settingsdesc">Swagger UI for every endpoint — useful for manual testing.</div>
            </div>
            <a className="btn btn-ghost" href={`${BASE_URL}/docs`} target="_blank" rel="noreferrer">
              Open /docs
            </a>
          </div>
        </div>
      </div>

      <div className="section">
        <div className="sectitle">About</div>
        <div className="card settingscard">
          <div className="aboutgrid" style={{ padding: '6px 0' }}>
            <div className="aboutitem">
              <b>Platform</b>
              HeartGuard AI · M2K HF-PULSE
            </div>
            <div className="aboutitem">
              <b>Version</b>
              v0.1.0
            </div>
            <div className="aboutitem">
              <b>Engine</b>
              Kitware Pulse 4.3.1 physiology simulation
            </div>
            <div className="aboutitem">
              <b>Purpose</b>
              Decision-support digital twin for early heart failure deterioration detection —
              not a diagnostic device.
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
