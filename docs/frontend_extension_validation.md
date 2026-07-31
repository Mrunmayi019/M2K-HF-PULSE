# Frontend Extension — Validation Record (Phase 7 continuation)

Status: done. This document records what was built, why, and exactly how it was verified, in the
same evidence-first convention as `methodology.md` §7/§8 — every claim below is backed by a
command actually run or a screen actually clicked through during this work, not asserted from
reading the code. See `methodology.md` §11 for the design summary this record supports.

## 1. Scope

The Phase 7 dashboard (`docs/methodology.md` §10) shipped with a sidebar listing five sections —
Patient Dashboard, Trends & History, Simulation Lab, Reports, Settings — but only the first was
wired to real content; the other four were static, non-interactive labels (`Sidebar.jsx`
hardcoded `className="navitem active"` on index 0 only, with no click handler). This work makes
all five functional, adds one small backend endpoint the new Trends page needed, and adds a
working dark-mode theme system across the whole app.

## 2. Backend addition

`GET /patients/{id}/wearable-history` (`src/api/routes.py`, `schemas.WearableHistoryResponse` in
`src/api/schemas.py`) returns every synced `WearableReading` row for a patient, ordered by
`recorded_date` ascending. This didn't exist before — the only prior wearable-read path was
`StatusResponse.latest_wearable`, a single most-recent row — and the new Trends & History page's
per-vital trend charts need the full multi-day series, not just the latest point.

**Test coverage** (`tests/test_api.py`, `TestWearableHistory`, 2 checks): unknown-patient 404, and
that readings for a known patient come back in chronological order with the correct count. Full
suite: **137/137 passed** (135 pre-existing + 2 new), run both on the host
(`pytest tests/ -v`) and confirmed against the rebuilt Docker image serving real traffic (§4).

## 3. Frontend additions

| File | What it is |
|---|---|
| `frontend/src/components/layout/Sidebar.jsx` (modified) | Nav items are now clickable (`onNavigate` callback + keyboard `Enter` support), highlight follows real `activeTab` state instead of a hardcoded index |
| `frontend/src/components/layout/AppShell.jsx` (modified) | Owns `activeTab` state and routes to one of 5 page components; owns theme state via `useTheme()` and passes it to Settings |
| `frontend/src/components/trends/TrendChart.jsx` (new) | Reusable single-series SVG line chart: 2px line, ~10%-opacity area wash, hairline gridlines, hover crosshair + snapped tooltip, 8px hit target via pointer tracking — sized to this project's own design tokens, not a charting library dependency |
| `frontend/src/components/trends/TrendsHistoryPage.jsx` (new) | Risk-score-over-time chart, a full assessment history table, and 6 per-vital `TrendChart`s over the synced wearable window |
| `frontend/src/hooks/useTrends.js` (new) | Fetches `/history` + `/wearable-history` for the selected patient |
| `frontend/src/components/lab/SimulationLabPage.jsx` (new) | A patient-creation wizard (demographics → optional clinical report → 21-day synthetic wearable trend) that drives the real API end-to-end, plus a "Simulation Internals" panel rendering the selected patient's raw `component_scores` breakdown as meters |
| `frontend/src/utils/syntheticTrend.js` (new) | Client-side 21-day wearable trend generator — linear interpolation between a start/end vitals snapshot plus small per-day noise, with 4 named presets (Stable / Mild Decline / Rapid Decline / Improving). This exists so a user can spin up a demo patient from the UI without hand-typing 21 days of readings; it is explicitly a UI convenience, not a new synthesis model — `src/data_synthesis/` remains the project's real, cited synthetic-population generator |
| `frontend/src/components/reports/ReportsPage.jsx` (new) | Master-detail list of every patient reusing the existing `DoctorReportCard` for the report preview/copy/download |
| `frontend/src/components/settings/SettingsPage.jsx` (new) | Theme toggle, a live backend "Test Connection" check (measures real round-trip latency against `GET /patients`), and an About panel |
| `frontend/src/hooks/useTheme.js` (new) | `system`/`light`/`dark`, persisted to `localStorage`, respects `prefers-color-scheme` when unset |
| `frontend/src/styles/theme.css` (modified) | Added `--text`/`--text2`/`--well`/`--zebra` tokens plus a `[data-theme='dark']` override block, and CSS for every component above |
| `frontend/src/components/condition/SeverityGauge.jsx` (modified) | One hardcoded light-mode stroke color fixed (§4.1) |
| `frontend/src/api/client.js` (modified) | Added `getHistory`, `getWearableHistory`, `createClinicalReport`, `syncWearableReading`; exported `BASE_URL` for the Settings page to display |

**Deliberate design choice — text tokens kept separate from `--navy`/`--navy2`.** The existing
palette already used `--navy`/`--navy2` for two unrelated purposes: body text color, and the fixed
dark background of always-dark surfaces (`.sidebar`, `.doccard`, `.btn-primary`). Overriding
`--navy` itself for dark mode would have inverted those surfaces too — turning the sidebar light
in dark mode, which is wrong (many dashboards, including this design's own reference, keep a fixed
dark nav rail regardless of theme). New `--text`/`--text2` tokens carry only the flippable
text-color role; `--navy`/`--navy2` keep backing the surfaces that must stay dark in both themes.

## 4. Issues found during verification (and fixed)

### 4.1 Chart gridlines and gauge track were hardcoded to light-mode hex colors

While manually clicking through dark mode (§5), `TrendChart`'s gridlines (`stroke="#e2e8f0"`),
its end-point/hover dot rings (`stroke="#fff"`), and `SeverityGauge`'s track circle
(`stroke="#EEF2F6"`) rendered as bright, high-contrast lines against the dark background —
violating the "hairline, recessive" gridline spec every other themed surface in this app follows.
**Root cause:** those three `<circle>`/`<line>` elements used literal hex values in SVG
presentation attributes instead of the new CSS custom properties. **Fix:** switched them to
`style={{ stroke: 'var(--line)' }}` / `var(--card)` / `var(--well)` (inline `style`, not a bare
`stroke="var(--line)"` attribute, for reliable custom-property resolution on SVG presentation
attributes). Re-verified in a real browser afterward (§5) — gridlines and rings now read as
subtle in both themes.

### 4.2 Missing trained ML models (found before this frontend work, fixed as a prerequisite)

Not a frontend bug, but recorded here because it blocked all real-data testing of the new pages
until fixed. `models/scenario_classifier.joblib` / `severity_regressor.joblib` are gitignored
(`models/*.joblib`, per `.gitignore`) and are baked into the backend image only via `COPY . .` at
build time (`backend/Dockerfile`) — there is no volume mount for `models/` in
`docker-compose.yml`, only `./data:/workspace/data`. On a fresh `docker compose up --build` with
no prior local training run, every background assessment pipeline crashed with
`FileNotFoundError: /workspace/models/scenario_classifier.joblib` the moment a patient's 21-day
window filled. **Fix:** run `python -m src.scenario_classifier.train` locally to produce the two
`.joblib` files, then `docker compose up -d --build pulse-backend` to rebuild the image with them
included. This is now also recorded in `docs/running_the_stack.md`'s Troubleshooting section so
it doesn't have to be rediscovered.

## 5. Manual verification performed

All of the following was done against the **real, running `docker compose` stack** (Postgres +
FastAPI/Pulse backend + Vite/nginx frontend), driving an actual Chrome browser via automation —
not a static render or a mocked build:

1. **Build/lint clean.** `npm run build` (Vite) and `npm run lint` (oxlint) both clean after every
   change; two pre-existing oxlint warnings (unused destructured variables) fixed along the way.
2. **All 5 tabs clicked through, light mode.** Patient Dashboard (unchanged, regression-checked),
   Trends & History (risk-score chart + 22-day real vitals history for a live patient, hover
   tooltip confirmed showing correct date/value snapped to the nearest point), Simulation Lab (form
   + presets + Simulation Internals meters for a live assessment), Reports (master-detail list,
   patient selection confirmed syncing with the sidebar's selection), Settings (theme switcher,
   connection test, about panel).
3. **All 5 tabs re-checked in dark mode** after toggling the theme, confirming the fix in §4.1 and
   that every card/table/input surface (backgrounds, borders, zebra striping, form inputs) follows
   the new tokens correctly, not just the pages introduced by this change.
4. **Theme persistence.** Verified `localStorage`-backed persistence survives a full page
   navigation/reload (dark mode remained active after `navigate()` to the app root).
5. **Live backend connection check.** Settings page's "Test Connection" button, which calls the
   real `GET /patients`, returned `Connected · 56ms` against the running stack.
6. **End-to-end Simulation Lab wizard test, no mocking.** Filled the wizard with age 68 / Male /
   172cm / 82kg, applied the "Rapid Decline" preset, and submitted. Confirmed: a new patient
   appeared in the sidebar in real time (`reload()` firing correctly after creation); all 21
   sequential `wearable-sync` calls succeeded (no error banner, success message rendered); the
   patient transitioned `collecting → pending → running` exactly as the existing status state
   machine (`methodology.md` §10, "State handling") predicts; `GET /status` for this patient
   confirmed `reading_count: 21` and the synced `latest_wearable` matched the Rapid Decline
   preset's day-21 values. The real Pulse simulation for this patient was left running in the
   background (not manually forced to complete) rather than blocking this verification pass on
   several minutes of wall-clock simulation time — consistent with how every other phase's
   Docker-dependent verification in `methodology.md` §7 is scoped (the pipeline being correctly
   *triggered* and *orchestrated* is the thing under test here, not Pulse's own physiology output,
   which is already covered by §4/§7's dedicated Pulse validation).
7. **Console check.** Browser console read back via automation after all of the above — zero
   JavaScript errors or exceptions.

## 6. What this record does not claim

Same discipline as `methodology.md` §8's Limitations section: this validates that the 4 new pages
render correctly, call the real API correctly, and don't regress the existing Patient Dashboard —
it does not add new coverage of Pulse's physiology output (already validated in §4/§7 of
`methodology.md`) or of the ML models' accuracy (already validated in §5/§7). No automated
frontend test suite was added here either, continuing the explicit decision already recorded in
`methodology.md` §10 ("What wasn't built, on purpose") — verification for `frontend/` remains
manual and browser-based across this project.
