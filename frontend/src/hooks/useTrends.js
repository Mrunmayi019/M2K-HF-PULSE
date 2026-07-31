import { useCallback, useEffect, useState } from 'react'
import { getHistory, getWearableHistory } from '../api/client.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

export function useTrends(patientId) {
  const [history, setHistory] = useState(null)
  const [wearableHistory, setWearableHistory] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    if (!patientId) return
    setLoading(true)
    setError(null)
    if (USE_MOCK) {
      setHistory({ patient_id: patientId, assessments: [] })
      setWearableHistory({ patient_id: patientId, readings: [] })
      setLoading(false)
      return
    }
    try {
      const [h, w] = await Promise.all([getHistory(patientId), getWearableHistory(patientId)])
      setHistory(h)
      setWearableHistory(w)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [patientId])

  useEffect(() => {
    load()
  }, [load])

  return { history, wearableHistory, loading, error, reload: load }
}
