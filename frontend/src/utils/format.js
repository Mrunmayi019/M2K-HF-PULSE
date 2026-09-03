// Real scenario_type values (CLAUDE.md's 5 locked scenario types) -> display metadata.
export const SCENARIOS = {
  stable: { name: 'Stable Compensated', icon: '✓', color: '#22C55E' },
  fluid_overload: { name: 'Fluid Overload', icon: '💧', color: '#0EA5E9' },
  cardiac_stress: { name: 'Cardiac Stress', icon: '⚡', color: '#EAB308' },
  deconditioning: { name: 'Deconditioning', icon: '↓', color: '#64748B' },
  acute_deterioration: { name: 'Acute Deterioration', icon: '⚠', color: '#EF4444' },
}

export const RISK_COLOR = { LOW: '#22C55E', MODERATE: '#EAB308', HIGH: '#EF4444' }

export function scenarioMeta(scenarioType) {
  return SCENARIOS[scenarioType] ?? { name: scenarioType ?? 'Unknown', icon: '?', color: '#64748B' }
}

export function riskColor(bucket) {
  return RISK_COLOR[bucket] ?? '#64748B'
}

// Patient model has no name field (anonymized digital-twin record) -- derive a stable,
// deterministic display label + avatar color/initials from the id instead of inventing a name.
export function avatarFromId(id) {
  let hash = 0
  for (let i = 0; i < id.length; i++) {
    hash = (hash * 31 + id.charCodeAt(i)) >>> 0
  }
  const hue = hash % 360
  return {
    color: `hsl(${hue}, 55%, 45%)`,
    initials: id.replace(/-/g, '').slice(0, 2).toUpperCase(),
    label: `Patient #${id.replace(/-/g, '').slice(-4).toUpperCase()}`,
  }
}

export function fmt1(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Math.round(n * 10) / 10
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  return (
    d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) +
    ' · ' +
    d.toLocaleDateString([], { month: 'short', day: 'numeric' })
  )
}

const VITAL_META = {
  resting_hr_bpm: { unit: 'bpm', label: 'Heart Rate' },
  spo2_pct: { unit: '%', label: 'SpO2' },
  weight_kg: { unit: 'kg', label: 'Weight' },
  steps_per_day: { unit: 'steps', label: 'Steps' },
  sleep_hours: { unit: 'hrs', label: 'Sleep' },
  hrv_rmssd_ms: { unit: 'ms', label: 'HRV (RMSSD)' },
}

export const VITAL_ORDER = [
  'resting_hr_bpm',
  'spo2_pct',
  'weight_kg',
  'steps_per_day',
  'sleep_hours',
  'hrv_rmssd_ms',
]

export function vitalMeta(key) {
  return VITAL_META[key]
}

// Worsening sign convention matches src/analytics/deterioration_rate.py's WORSENING_SIGN --
// +1 means a rising slope is worsening, -1 means a falling slope is worsening.
const WORSENING_SIGN = {
  resting_hr_bpm: 1,
  spo2_pct: -1,
  weight_kg: 1,
  steps_per_day: -1,
  sleep_hours: -1,
  hrv_rmssd_ms: -1,
}

export function trendDirection(key, slope) {
  if (slope === null || slope === undefined) return { arrow: '—', worsening: false }
  const sign = WORSENING_SIGN[key] ?? 1
  const worsening = Math.sign(slope) === Math.sign(sign) && slope !== 0
  return { arrow: slope > 0 ? '↑' : slope < 0 ? '↓' : '—', worsening }
}
