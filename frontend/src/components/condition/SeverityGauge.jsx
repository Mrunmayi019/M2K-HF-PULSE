export default function SeverityGauge({ severity, color = '#64748B' }) {
  const r = 28
  const cx = 32
  const cy = 32
  const circ = 2 * Math.PI * r
  const clamped = severity === null || severity === undefined ? 0 : Math.max(0, Math.min(1, severity))

  return (
    <svg width={64} height={64} viewBox="0 0 64 64" style={{ flex: 'none' }}>
      <circle cx={cx} cy={cy} r={r} fill="none" style={{ stroke: 'var(--well)' }} strokeWidth={7} />
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill="none"
        stroke={color}
        strokeWidth={7}
        strokeLinecap="round"
        strokeDasharray={circ}
        strokeDashoffset={circ * (1 - clamped)}
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: 'stroke-dashoffset 0.6s ease' }}
      />
    </svg>
  )
}
