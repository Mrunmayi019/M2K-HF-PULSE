import { useMemo, useRef, useState } from 'react'

// Single-series line chart: 2px line, ~10% area wash, hairline gridlines, hover crosshair +
// tooltip snapped to the nearest point. Per dataviz skill's mark spec -- no legend box (single
// series, the card title already names it).
export default function TrendChart({ data, color = '#14B8A6', unit = '', height = 120, formatX, formatY }) {
  const wrapRef = useRef(null)
  const [hoverIdx, setHoverIdx] = useState(null)
  const width = 560
  const padL = 8
  const padR = 8
  const padT = 12
  const padB = 22

  const clean = useMemo(() => (data ?? []).filter((d) => d.y !== null && d.y !== undefined), [data])

  const { points, gridLines } = useMemo(() => {
    if (clean.length === 0) return { points: [], gridLines: [] }
    const ys = clean.map((d) => d.y)
    let lo = Math.min(...ys)
    let hi = Math.max(...ys)
    if (lo === hi) {
      lo -= 1
      hi += 1
    }
    const pad = (hi - lo) * 0.12
    lo -= pad
    hi += pad
    const innerW = width - padL - padR
    const innerH = height - padT - padB
    const pts = clean.map((d, i) => ({
      ...d,
      px: padL + (clean.length === 1 ? innerW / 2 : (i / (clean.length - 1)) * innerW),
      py: padT + innerH - ((d.y - lo) / (hi - lo)) * innerH,
    }))
    const lines = [lo + (hi - lo) * 0.2, lo + (hi - lo) * 0.5, lo + (hi - lo) * 0.8].map((v) => ({
      v,
      py: padT + innerH - ((v - lo) / (hi - lo)) * innerH,
    }))
    return { points: pts, gridLines: lines }
  }, [clean, height])

  if (clean.length === 0) {
    return (
      <div className="trendchart-empty" style={{ height }}>
        No data yet
      </div>
    )
  }

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.px.toFixed(2)},${p.py.toFixed(2)}`).join(' ')
  const areaPath = `${linePath} L${points[points.length - 1].px.toFixed(2)},${height - padB} L${points[0].px.toFixed(2)},${height - padB} Z`
  const last = points[points.length - 1]
  const hovered = hoverIdx !== null ? points[hoverIdx] : null

  function handleMove(e) {
    if (points.length === 0) return
    const rect = wrapRef.current.getBoundingClientRect()
    const relX = ((e.clientX - rect.left) / rect.width) * width
    let nearest = 0
    let best = Infinity
    points.forEach((p, i) => {
      const d = Math.abs(p.px - relX)
      if (d < best) {
        best = d
        nearest = i
      }
    })
    setHoverIdx(nearest)
  }

  return (
    <div className="trendchart" ref={wrapRef}>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        width="100%"
        height={height}
        onPointerMove={handleMove}
        onPointerLeave={() => setHoverIdx(null)}
        style={{ display: 'block', touchAction: 'none' }}
      >
        {gridLines.map((g) => (
          <line key={g.v} x1={padL} x2={width - padR} y1={g.py} y2={g.py} style={{ stroke: 'var(--line)' }} strokeWidth={1} />
        ))}
        <path d={areaPath} fill={color} opacity={0.1} stroke="none" />
        <path d={linePath} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={last.px} cy={last.py} r={4} fill={color} style={{ stroke: 'var(--card)' }} strokeWidth={2} />
        {hovered && (
          <>
            <line x1={hovered.px} x2={hovered.px} y1={padT} y2={height - padB} style={{ stroke: 'var(--muted)' }} strokeWidth={1} strokeDasharray="3,3" />
            <circle cx={hovered.px} cy={hovered.py} r={4} fill={color} style={{ stroke: 'var(--card)' }} strokeWidth={2} />
          </>
        )}
      </svg>
      <div className="trendchart-tooltip" style={{ opacity: hovered ? 1 : 0, left: `${((hovered?.px ?? 0) / width) * 100}%` }}>
        {hovered && (
          <>
            <div className="tt-val">
              {formatY ? formatY(hovered.y) : hovered.y}
              {unit}
            </div>
            <div className="tt-x">{formatX ? formatX(hovered.x) : hovered.x}</div>
          </>
        )}
      </div>
      <div className="trendchart-axis">
        <span>{formatX ? formatX(clean[0].x) : clean[0].x}</span>
        <span>{formatX ? formatX(clean[clean.length - 1].x) : clean[clean.length - 1].x}</span>
      </div>
    </div>
  )
}
