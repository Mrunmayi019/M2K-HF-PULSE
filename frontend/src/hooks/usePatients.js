import { useCallback, useEffect, useState } from 'react'
import { listPatients, getReport } from '../api/client.js'
import { MOCK_PATIENTS, MOCK_REPORTS } from '../mock/mockData.js'

const USE_MOCK = import.meta.env.VITE_USE_MOCK === 'true'

// Sidebar needs a per-patient risk-bucket summary, but there's no list-with-summary endpoint --
// GET /patients then GET .../report per patient (fine at demo scale; see Phase 7 plan).
export function usePatients() {
  const [patients, setPatients] = useState(null)
  const [reports, setReports] = useState({})
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setError(null)
    if (USE_MOCK) {
      setPatients(MOCK_PATIENTS)
      setReports(MOCK_REPORTS)
      return
    }
    try {
      const list = await listPatients()
      setPatients(list)
      const entries = await Promise.all(
        list.map(async (p) => {
          try {
            return [p.id, await getReport(p.id)]
          } catch {
            return [p.id, null]
          }
        }),
      )
      setReports(Object.fromEntries(entries))
    } catch (err) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return { patients, reports, error, reload: load }
}
