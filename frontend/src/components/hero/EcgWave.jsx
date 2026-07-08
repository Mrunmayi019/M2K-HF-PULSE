import { useEffect, useRef, useState } from 'react'

// Ported from the decoded design reference's buildEcgPath()/componentDidMount() rAF loop.
function buildEcgPath(w, h, amp) {
  const pts = []
  const cycles = 3
  const cw = w / cycles
  for (let c = 0; c < cycles; c++) {
    const baseX = c * cw
    pts.push(
      [baseX, h / 2],
      [baseX + cw * 0.12, h / 2],
      [baseX + cw * 0.16, h / 2 - amp * 0.15],
      [baseX + cw * 0.2, h / 2 + amp * 0.1],
      [baseX + cw * 0.24, h / 2],
      [baseX + cw * 0.3, h / 2],
      [baseX + cw * 0.34, h / 2 - amp * 0.9],
      [baseX + cw * 0.38, h / 2 + amp * 0.5],
      [baseX + cw * 0.42, h / 2],
      [baseX + cw * 0.55, h / 2],
      [baseX + cw * 0.62, h / 2 - amp * 0.35],
      [baseX + cw * 0.7, h / 2],
      [baseX + cw, h / 2],
    )
  }
  return 'M' + pts.map((p) => p[0] + ',' + p[1]).join(' L')
}

export default function EcgWave({ color = '#22C55E', width = 260, height = 70 }) {
  const [offset, setOffset] = useState(0)
  const rafRef = useRef(null)

  useEffect(() => {
    const tick = () => {
      setOffset((prev) => (prev + 1.4) % 400)
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(rafRef.current)
  }, [])

  const path = buildEcgPath(width * 2, height, 26)

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ overflow: 'hidden' }}>
      <defs>
        <clipPath id="ecgclip">
          <rect x={0} y={0} width={width} height={height} />
        </clipPath>
      </defs>
      <g clipPath="url(#ecgclip)" transform={`translate(${-(offset / 400) * width * 2},0)`}>
        <path d={path} fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" opacity={0.85} />
      </g>
    </svg>
  )
}
