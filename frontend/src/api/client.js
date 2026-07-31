export const BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

async function request(path, options) {
  let res
  try {
    res = await fetch(`${BASE_URL}${path}`, options)
  } catch (err) {
    throw new Error(`Network error reaching ${BASE_URL}${path}: ${err.message}`)
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ? JSON.stringify(body.detail) : detail
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new Error(`${res.status} ${detail}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export function listPatients() {
  return request('/patients')
}

export function createPatient(payload) {
  return request('/patients', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function getReport(patientId) {
  return request(`/patients/${patientId}/report`)
}

export function getStatus(patientId) {
  return request(`/patients/${patientId}/status`)
}

export function getHistory(patientId) {
  return request(`/patients/${patientId}/history`)
}

export function getWearableHistory(patientId) {
  return request(`/patients/${patientId}/wearable-history`)
}

export function createClinicalReport(patientId, payload) {
  return request(`/patients/${patientId}/clinical-report`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export function syncWearableReading(patientId, payload) {
  return request(`/patients/${patientId}/wearable-sync`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}
