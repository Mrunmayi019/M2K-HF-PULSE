import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isDefaultFlags } from './twinState.js'

const DEFAULTS = {
  PIPELINE_MODE: 'fresh',
  ENABLE_BCG_MODIFIERS: false,
  ENABLE_HR_BASELINE: false,
  ENABLE_ALERT_HYSTERESIS: false,
  ENABLE_SCENARIO_PERSISTENCE: false,
}

test('all defaults (or no flags at all) hide the twin-state panel', () => {
  assert.equal(isDefaultFlags(DEFAULTS), true)
  assert.equal(isDefaultFlags(null), true)
})

test('continuous mode or any feature on shows it', () => {
  assert.equal(isDefaultFlags({ ...DEFAULTS, PIPELINE_MODE: 'continuous' }), false)
  for (const k of Object.keys(DEFAULTS).filter((k) => k !== 'PIPELINE_MODE')) {
    assert.equal(isDefaultFlags({ ...DEFAULTS, [k]: true }), false, k)
  }
})
