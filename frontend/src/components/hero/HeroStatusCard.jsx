import EcgWave from './EcgWave.jsx'
import { riskColor } from '../../utils/format.js'

const HERO_SUMMARY = {
  LOW: 'This patient is stable — no action needed beyond routine monitoring.',
  MODERATE: 'Some signs of strain detected — monitor closely and review symptoms.',
  HIGH: 'Significant deterioration detected — clinical follow-up is recommended today.',
}

const GENERIC_WARNING = {
  LOW: 'Model confidence is high. Continue daily wearable syncing for best accuracy.',
  MODERATE: 'Trends suggest early strain. A closer review may be warranted at the next visit.',
  HIGH: 'This projection indicates rapid decompensation risk. This is a decision-support estimate only — seek clinical evaluation promptly.',
}

export default function HeroStatusCard({ assessment, patientLabel }) {
  const riskBucket = assessment?.risk_bucket ?? null
  const color = riskColor(riskBucket)
  const isHigh = riskBucket === 'HIGH'
  const warningText = assessment?.risk_caveats || (riskBucket ? GENERIC_WARNING[riskBucket] : null)

  return (
    <div className="section">
      <div
        className={`card hero ${isHigh ? 'risk-high' : ''}`}
        style={{ borderColor: `${color}55` }}
      >
        <div className="herotop">
          <div>
            <div className="riskbadge" style={{ background: `${color}1A`, color }}>
              <span className="pill-dot" />
              {riskBucket ? `${riskBucket} RISK` : 'NO ASSESSMENT YET'}
            </div>
            <div className="badgerow">
              {assessment?.nyha_class && <span className="tag">NYHA Class {assessment.nyha_class}</span>}
            </div>
            <div className="heroname">{patientLabel}</div>
            <div className="herosummary">
              {riskBucket ? HERO_SUMMARY[riskBucket] : 'Waiting for the first completed simulation.'}
            </div>
          </div>
          <div className="ecgwrap">
            <EcgWave color={color === '#64748B' ? '#94A3B8' : color} />
          </div>
        </div>
        {warningText && (
          <div
            className="warnbanner"
            style={{
              background: `${color}0F`,
              color: color === '#22C55E' ? '#166534' : color === '#EAB308' ? '#854D0E' : '#B91C1C',
              border: `1px solid ${color}33`,
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" style={{ flex: 'none', marginTop: 1 }}>
              <path d="M12 3l10 18H2L12 3z" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
              <path d="M12 10v4M12 17.5v.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            <div>{warningText}</div>
          </div>
        )}
      </div>
    </div>
  )
}
