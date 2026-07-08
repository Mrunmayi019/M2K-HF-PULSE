import { useCallback, useEffect, useRef, useState } from 'react'
import { getReport } from '../api/client.js'
import { MOCK_REPORTS } from '../mock/mockData.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'
const POLL_INTERVAL_MS = 4000

export function usePatientReport(patientId) {
  const [report, setReport] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  const fetchOnce = useCallback(
    async (opts = {}) => {
      if (!patientId) return
      if (opts.showRefreshing) setRefreshing(true)
      try {
        const data = USE_MOCK ? MOCK_REPORTS[patientId] : await getReport(patientId)
        setReport(data)
        setError(null)
      } catch (err) {
        setError(err.message)
      } finally {
        setLoading(false)
        if (opts.showRefreshing) setRefreshing(false)
      }
    },
    [patientId],
  )

  useEffect(() => {
    setLoading(true)
    setReport(null)
    setError(null)
    fetchOnce()
  }, [patientId, fetchOnce])

  useEffect(() => {
    const status = report?.status?.simulation_status
    const shouldPoll = status === 'running' || status === 'pending'
    if (pollRef.current) clearInterval(pollRef.current)
    if (shouldPoll) {
      pollRef.current = setInterval(() => fetchOnce(), POLL_INTERVAL_MS)
    }
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [report?.status?.simulation_status, fetchOnce])

  const refresh = useCallback(() => fetchOnce({ showRefreshing: true }), [fetchOnce])

  return { report, loading, refreshing, error, refresh }
}
