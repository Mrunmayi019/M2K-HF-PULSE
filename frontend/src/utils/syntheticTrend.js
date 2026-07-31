// Client-side 21-day wearable trend generator for the Simulation Lab -- lets a user spin up a
// demo patient without hand-entering 21 days of readings. Linearly interpolates between a start
// and end vitals snapshot (with light noise), the same shape src/data_synthesis produces server-side,
// just simulated in the browser instead of pandas.
export const TREND_PRESETS = {
  stable: {
    label: 'Stable',
    start: { hr: 72, spo2: 97, weightDelta: 0, steps: 7500, sleep: 7.0, hrv: 32 },
    end: { hr: 73, spo2: 97, weightDelta: 0.1, steps: 7300, sleep: 6.9, hrv: 31 },
  },
  mild_decline: {
    label: 'Mild Decline',
    start: { hr: 74, spo2: 96.5, weightDelta: 0, steps: 7000, sleep: 7.0, hrv: 30 },
    end: { hr: 84, spo2: 95.5, weightDelta: 1.2, steps: 5500, sleep: 6.3, hrv: 24 },
  },
  rapid_decline: {
    label: 'Rapid Decline',
    start: { hr: 76, spo2: 96, weightDelta: 0, steps: 6500, sleep: 6.5, hrv: 28 },
    end: { hr: 120, spo2: 90, weightDelta: 3.5, steps: 2000, sleep: 4.5, hrv: 12 },
  },
  improving: {
    label: 'Improving',
    start: { hr: 82, spo2: 94, weightDelta: 1.5, steps: 4500, sleep: 5.5, hrv: 18 },
    end: { hr: 70, spo2: 97.5, weightDelta: 0, steps: 7500, sleep: 7.2, hrv: 28 },
  },
}

const NOISE = { hr: 1.5, spo2: 0.3, weight: 0.15, steps: 400, sleep: 0.3, hrv: 1.5 }

function clamp(v, lo, hi) {
  return Math.max(lo, Math.min(hi, v))
}

function lerp(a, b, t) {
  return a + (b - a) * t
}

export function generateTrend({ start, end, weightKg, days = 21 }) {
  const startDate = new Date()
  startDate.setDate(startDate.getDate() - days)

  return Array.from({ length: days }, (_, i) => {
    const t = days === 1 ? 1 : i / (days - 1)
    const date = new Date(startDate)
    date.setDate(date.getDate() + i)
    const noise = (mag) => (Math.random() - 0.5) * 2 * mag

    return {
      recorded_date: date.toISOString().slice(0, 10),
      resting_hr_bpm: Math.round(clamp(lerp(start.hr, end.hr, t) + noise(NOISE.hr), 20, 250) * 10) / 10,
      spo2_pct: Math.round(clamp(lerp(start.spo2, end.spo2, t) + noise(NOISE.spo2), 50, 100) * 10) / 10,
      weight_kg: Math.round(clamp(weightKg + lerp(start.weightDelta, end.weightDelta, t) + noise(NOISE.weight), 20, 300) * 10) / 10,
      steps_per_day: Math.round(clamp(lerp(start.steps, end.steps, t) + noise(NOISE.steps), 0, 100000)),
      sleep_hours: Math.round(clamp(lerp(start.sleep, end.sleep, t) + noise(NOISE.sleep), 0, 24) * 10) / 10,
      hrv_rmssd_ms: Math.round(clamp(lerp(start.hrv, end.hrv, t) + noise(NOISE.hrv), 0, 300) * 10) / 10,
    }
  })
}
