// Run with `npm test` (Node's built-in test runner, no extra dependencies).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { heroSummary, ALERT_SUMMARY, SIGNALS_DISAGREE_SUMMARY, NO_ASSESSMENT_SUMMARY } from './heroSummary.js'

test('signals disagree: never the twin-only "stable — no action needed" line', () => {
  const line = heroSummary('NONE', true)
  assert.equal(line, SIGNALS_DISAGREE_SUMMARY)
  assert.doesNotMatch(line, /stable|no action needed/i)
})

test('signals disagree overrides every twin level', () => {
  for (const level of ['ALERT', 'WATCH', 'NONE']) assert.equal(heroSummary(level, true), SIGNALS_DISAGREE_SUMMARY)
})

test('signals agree (or unknown): the twin level summary is unchanged', () => {
  for (const level of ['ALERT', 'WATCH', 'NONE']) {
    assert.equal(heroSummary(level, false), ALERT_SUMMARY[level])
    assert.equal(heroSummary(level, null), ALERT_SUMMARY[level])
    assert.equal(heroSummary(level, undefined), ALERT_SUMMARY[level])
  }
})

test('no assessment yet', () => {
  assert.equal(heroSummary(null, true), NO_ASSESSMENT_SUMMARY)
  assert.equal(heroSummary(undefined, undefined), NO_ASSESSMENT_SUMMARY)
})
