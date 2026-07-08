// Mock data shaped exactly like the *extended* Phase 6 API responses (see
// docs/methodology.md / src/api/schemas.py after the Phase 7 additions), so that swapping this
// for real fetch calls in step 2 is a data-source change, not a component rebuild.

export const MOCK_PATIENTS = [
  { id: '11111111-1111-4111-8111-111111111111', age: 74, sex: 'Female', height_cm: 162, weight_kg: 71, created_at: '2026-06-01T09:00:00Z' },
  { id: '22222222-2222-4222-8222-222222222222', age: 68, sex: 'Male', height_cm: 178, weight_kg: 84, created_at: '2026-06-02T09:00:00Z' },
  { id: '33333333-3333-4333-8333-333333333333', age: 81, sex: 'Female', height_cm: 158, weight_kg: 60, created_at: '2026-06-03T09:00:00Z' },
  { id: '44444444-4444-4444-8444-444444444444', age: 59, sex: 'Male', height_cm: 174, weight_kg: 90, created_at: '2026-06-04T09:00:00Z' },
]

function makeReport({ patientId, scenario, severity, riskBucket, riskScore, nyha, ef, bnp, hr, spo2, weight, steps, sleep, hrv, caveats, direction, daysToNext, simStatus, errorMessage }) {
  const latestWearable = simStatus === 'collecting' || simStatus === 'pending' || simStatus === 'running' || simStatus === 'complete' || simStatus === 'failed'
    ? {
        recorded_date: '2026-07-08',
        resting_hr_bpm: hr,
        spo2_pct: spo2,
        weight_kg: weight,
        steps_per_day: steps,
        sleep_hours: sleep,
        hrv_rmssd_ms: hrv,
      }
    : null

  const latestAssessment =
    simStatus === 'complete'
      ? {
          risk_score: riskScore,
          risk_bucket: riskBucket,
          component_scores: {
            hr_rise: 0.08,
            map_drop: 0.06,
            co_drop_pct: 0.05,
            compensation_flag: 0.1,
            instability_flag: riskBucket === 'HIGH' ? 0.3 : 0,
          },
          nyha_class: nyha,
          risk_caveats: caveats ?? null,
          deterioration_direction: direction,
          days_to_next_stage: daysToNext,
          scenario_type: scenario,
          severity,
          ejection_fraction_pct: ef,
          nt_probnp_pg_ml: bnp,
          vital_slopes: {
            resting_hr_bpm: 0.8,
            spo2_pct: -0.15,
            weight_kg: 0.12,
            steps_per_day: -120,
            sleep_hours: -0.05,
            hrv_rmssd_ms: -0.6,
          },
          created_at: '2026-07-08T09:15:00Z',
        }
      : null

  const horizons =
    simStatus === 'complete'
      ? {
          7: { projected_severity: Math.min(1, severity + 0.03), risk_score: riskScore, risk_bucket: riskBucket, status: 'ok' },
          14: { projected_severity: Math.min(1, severity + 0.07), risk_score: riskScore, risk_bucket: riskBucket, status: 'ok' },
          30: { projected_severity: Math.min(1, severity + 0.15), risk_score: riskScore, risk_bucket: riskBucket, status: 'ok' },
        }
      : null

  return {
    patient_id: patientId,
    status: {
      patient_id: patientId,
      simulation_status: simStatus,
      reading_count: simStatus === 'collecting' ? 12 : 21,
      latest_assessment: latestAssessment,
      latest_wearable: latestWearable,
      error_message: errorMessage ?? null,
    },
    projection: {
      patient_id: patientId,
      available: horizons !== null,
      horizons,
    },
  }
}

export const MOCK_REPORTS = {
  '11111111-1111-4111-8111-111111111111': makeReport({
    patientId: '11111111-1111-4111-8111-111111111111',
    scenario: 'fluid_overload',
    severity: 0.52,
    riskBucket: 'MODERATE',
    riskScore: 0.48,
    nyha: 'III',
    ef: 38,
    bnp: 640,
    hr: 88,
    spo2: 95,
    weight: 71.4,
    steps: 3200,
    sleep: 6.4,
    hrv: 28,
    caveats:
      'Detected scenario is fluid_overload -- risk_score is known to underestimate severity for this presentation (see docs/methodology.md §6.1). Do not rely on risk_score alone.',
    direction: 'worsening',
    daysToNext: 12,
    simStatus: 'complete',
  }),
  '22222222-2222-4222-8222-222222222222': makeReport({
    patientId: '22222222-2222-4222-8222-222222222222',
    scenario: 'stable',
    severity: 0.18,
    riskBucket: 'LOW',
    riskScore: 0.15,
    nyha: 'I',
    ef: 52,
    bnp: 180,
    hr: 68,
    spo2: 98,
    weight: 84.1,
    steps: 8100,
    sleep: 7.6,
    hrv: 44,
    direction: 'stable',
    daysToNext: null,
    simStatus: 'complete',
  }),
  '33333333-3333-4333-8333-333333333333': makeReport({
    patientId: '33333333-3333-4333-8333-333333333333',
    scenario: 'acute_deterioration',
    severity: 0.86,
    riskBucket: 'HIGH',
    riskScore: 0.81,
    nyha: 'IV',
    ef: 24,
    bnp: 1420,
    hr: 112,
    spo2: 89,
    weight: 61.2,
    steps: 900,
    sleep: 5.1,
    hrv: 16,
    direction: 'worsening',
    daysToNext: 3,
    simStatus: 'complete',
  }),
  '44444444-4444-4444-8444-444444444444': makeReport({
    patientId: '44444444-4444-4444-8444-444444444444',
    scenario: null,
    severity: null,
    riskBucket: null,
    riskScore: null,
    nyha: null,
    ef: null,
    bnp: null,
    hr: 96,
    spo2: 94,
    weight: 90.3,
    steps: 4400,
    sleep: 6.9,
    hrv: 31,
    simStatus: 'collecting',
  }),
}
