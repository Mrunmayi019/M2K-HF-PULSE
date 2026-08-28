import { useMemo } from 'react'

// Pressure-volume (PV) loop: a closed cycle plot, volume (x) vs pressure (y), for one cardiac
// cycle -- unlike every other chart in this app, both axes carry real physiological units and
// are shown explicitly (a PV loop is meaningless without them: its width is stroke volume, its
// height is pulse pressure, per src.analytics.simulation_features.extract_waveform_data()).
export default function PVLoopChart({ points, color = '#14B8A6', height = 200 }) {
  const width = 320
  const padL = 46
  const padR = 14
  const padT = 12
  const padB = 30

  const clean = useMemo(() => (points ?? []).filter((p) => p.volume_ml != null && p.pressure_mmhg != null), [points])

  const { path, xTicks, yTicks } = useMemo(() => {
    if (clean.length < 2) return { path: '', xTicks: [], yTicks: [] }
    const vols = clean.map((p) => p.volume_ml)
    const press = clean.map((p) => p.pressure_mmhg)
    let vLo = Math.min(...vols)
    let vHi = Math.max(...vols)
    let pLo = Math.min(...press)
    let pHi = Math.max(...press)
    const vPad = (vHi - vLo) * 0.12 || 1
    const pPad = (pHi - pLo) * 0.12 || 1
    vLo -= vPad
    vHi += vPad
    pLo -= pPad
    pHi += pPad
    const innerW = width - padL - padR
    const innerH = height - padT - padB
    const toX = (v) => padL + ((v - vLo) / (vHi - vLo)) * innerW
    const toY = (p) => padT + innerH - ((p - pLo) / (pHi - pLo)) * innerH

    const d = clean.map((pt, i) => `${i === 0 ? 'M' : 'L'}${toX(pt.volume_ml).toFixed(2)},${toY(pt.pressure_mmhg).toFixed(2)}`).join(' ') + ' Z'

    const xTicks = [vLo + vPad, (vLo + vHi) / 2, vHi - vPad].map((v) => ({ v, px: toX(v) }))
    const yTicks = [pLo + pPad, (pLo + pHi) / 2, pHi - pPad].map((p) => ({ p, py: toY(p) }))
    return { path: d, xTicks, yTicks }
  }, [clean, height])

  if (clean.length < 2) {
    return (
      <div className="trendchart-empty" style={{ height }}>
        No PV loop data
      </div>
    )
  }

  return (
    <div className="pvloopchart">
      <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} style={{ display: 'block' }}>
        {yTicks.map((t) => (
          <line key={`y${t.p}`} x1={padL} x2={width - padR} y1={t.py} y2={t.py} style={{ stroke: 'var(--line)' }} strokeWidth={1} />
        ))}
        {yTicks.map((t) => (
          <text key={`yl${t.p}`} x={padL - 6} y={t.py + 3} textAnchor="end" style={{ fontSize: 9, fill: 'var(--muted)' }}>
            {Math.round(t.p)}
          </text>
        ))}
        {xTicks.map((t) => (
          <text key={`xl${t.v}`} x={t.px} y={height - padB + 14} textAnchor="middle" style={{ fontSize: 9, fill: 'var(--muted)' }}>
            {Math.round(t.v)}
          </text>
        ))}
        <path d={path} fill={color} opacity={0.12} stroke={color} strokeWidth={2} strokeLinejoin="round" />
      </svg>
      <div className="pvloopchart-axislabels">
        <span>Volume (mL) &rarr;</span>
        <span className="pvloopchart-ylabel">Pressure (mmHg) &uarr;</span>
      </div>
    </div>
  )
}
