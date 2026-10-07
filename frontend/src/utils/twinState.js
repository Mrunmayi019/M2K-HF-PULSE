// feature/wire-research-features. True when every research flag is at its default (fresh pipeline,
// every experimental feature off) -- the dashboard then shows no twin-state panel at all, so the
// default app looks exactly as it did before the flags existed.
export function isDefaultFlags(flags) {
  if (!flags) return true
  return Object.entries(flags).every(([k, v]) => (k === 'PIPELINE_MODE' ? v === 'fresh' : v === false))
}
