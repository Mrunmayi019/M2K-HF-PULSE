# Running the Full Stack (Docker)

Step-by-step guide to running the whole system locally — Postgres + FastAPI/Pulse backend +
React frontend — via `docker compose`, verifying each piece actually works, and troubleshooting
the two real issues that came up getting this working (documented here so nobody has to
rediscover them). See `docker-compose.yml`, `backend/Dockerfile`, and `frontend/Dockerfile` for
the full technical reasoning behind each design choice; this doc is the operational walkthrough.

## Prerequisites

- **Docker Desktop installed and running** — not just installed. Check with `docker ps`; if it
  says `Cannot connect to the Docker daemon`, open Docker Desktop and wait for it to finish
  starting before continuing.
- Repo cloned, terminal open at the repo root.

## Step 1 — Build and start everything

```bash
docker compose up --build
```

Run this in the foreground (no `-d`) the first time so you can see the logs. First run takes
10-20+ minutes: it builds two images from scratch, pulls Postgres, and — because the backend
image pulls `kitware/pulse:4.3.1`, which only ships an `amd64` build — runs under emulation on
Apple Silicon Macs. **The "requested image's platform ... does not match the detected host
platform" warning during the build is expected, not an error.**

What you should see, roughly in order:
1. `db` pulling `postgres:15-alpine`
2. `pulse-backend` building: pulls `kitware/pulse:4.3.1`, then `python:3.11-slim`, installs system
   packages, then `pip install -r requirements.txt` (slowest step — scikit-learn/xgboost are large)
3. `frontend` building: pulls `node:20-alpine`, `npm ci`, `vite build`, then `nginx:alpine`
4. `db` logs `database system is ready to accept connections`
5. `pulse-backend` logs something ending in `Application startup complete`
6. `frontend`'s nginx starts almost instantly

**If `pulse-backend` prints a Python traceback and restarts in a loop** instead of reaching
"Application startup complete," it crashed before uvicorn came up — usually a database
connection issue. Check `docker compose logs pulse-backend`.

## Step 2 — Confirm all three containers are actually running

In a **second terminal** (leave the first showing logs):

```bash
docker compose ps
```

All three (`db`, `pulse-backend`, `frontend`) should show `Up` (`healthy` for `db`). Anything
showing `Restarting` or `Exited` is crash-looping — `docker compose logs <service-name>` to see why.

## Step 3 — Confirm the backend is reachable

Open **http://localhost:8000/docs** — the FastAPI Swagger UI should load, listing every endpoint.
If this loads, uvicorn is up and the app's startup hook successfully connected to Postgres (it
would have crashed on startup otherwise).

## Step 4 — Confirm the frontend is reachable

Open **http://localhost:3000** — the dashboard shell should load (empty patient list is expected
on a fresh database).

## Step 5 — Smoke-test the real Pulse pipeline

This is the checkpoint that actually matters: it confirms the Pulse physiology engine executes
correctly *inside* the container, not just that the web server is up. `scripts/docker_smoke_test.sh`
creates one real patient, feeds it a full 21-day wearable window through the live API, and polls
until the real (non-mocked) background pipeline — which makes 4 real Pulse simulation calls —
completes.

```bash
bash scripts/docker_smoke_test.sh
```

Run this with `bash` explicitly, regardless of what shell you normally use (fish, zsh, etc.) — the
script uses bash-specific syntax that won't parse the same way in every shell.

It will:
1. Create a patient and print its ID
2. Submit a clinical report and sync 21 days of wearable data
3. Print `status: running`/`pending` every 15 seconds while the real pipeline runs in the
   background — **this can take up to ~10 minutes under Docker's arm64→amd64 emulation on Apple
   Silicon; that is expected, not a hang**
4. Print `status: complete` (or `failed`) and dump the final patient report as JSON

**Reading the result:**
- `status: complete` with a real `risk_bucket`/`nyha_class` in the final JSON → everything works.
  Refresh http://localhost:3000 and the patient should appear in the sidebar.
- `status: failed` → the `error_message` field in that same JSON says exactly why (see
  Troubleshooting below for the specific error we hit and fixed).
- Stuck past ~15 minutes → check `docker compose logs pulse-backend` for a stack trace.

## Shutting down / resetting

```bash
docker compose down        # stops everything, keeps the Postgres data volume
docker compose down -v     # also wipes the Postgres volume -- start completely fresh next time
```

## Troubleshooting

Two real issues came up building this stack the first time. Both are already fixed in the
committed `Dockerfile`s — this section exists so that if either resurfaces (e.g. after someone
edits a Dockerfile, or on a teammate's machine with a different Docker Desktop version), it's
fast to recognize and fix rather than re-debugged from scratch.

### `frontend` build fails: "Vite requires Node.js version 20.19+ or 22.12+"

This project's `frontend/package.json` pins `vite ^8.1.1`, which needs a newer Node than
`node:18-alpine`. Fixed by using `node:20-alpine` in `frontend/Dockerfile`'s build stage — if you
see this error, check that line hasn't been reverted. (The same version is set in
`.github/workflows/ci.yml`'s `setup-node` step, for the same reason.)

### Pulse fails inside the container: `error while loading shared libraries: lib*.so.* not found`

`PulseScenarioDriver` is a compiled C++ binary; `python:3.11-slim` strips most non-Python system
libraries, so the backend image has to explicitly install whatever Pulse was actually linked
against. We hit this once for `libc++.so.1`/`libc++abi.so.1` (Pulse was built against LLVM's C++
runtime, not GCC's `libstdc++`) — both are now installed via `apt-get` in `backend/Dockerfile`.

**If you see this error again** (a different missing library), get the *complete* list in one
shot rather than fixing libraries one at a time across multiple rebuild cycles:

```bash
docker compose exec pulse-backend ldd /pulse/bin/PulseScenarioDriver
```

Every line ending in `=> not found` is a missing library. Map it to a Debian/Ubuntu package name
(usually `apt-cache search <library-name-without-.so>` inside the container, or a quick web
search — e.g. `libc++.so.1` → package `libc++1`) and add it to the `apt-get install` list in
`backend/Dockerfile`, then rebuild.

### Background pipeline crashes: `FileNotFoundError: /workspace/models/scenario_classifier.joblib`

The trained ML models (`models/scenario_classifier.joblib`, `models/severity_regressor.joblib`)
are gitignored (`models/*.joblib`) and are **not** volume-mounted into `pulse-backend` — only
`./data:/workspace/data` is (see `docker-compose.yml`). They're baked into the image at build time
via `backend/Dockerfile`'s `COPY . .`, which means they have to already exist locally *before*
`docker compose up --build` for the very first time. If they don't, every patient's background
assessment pipeline (triggered once a 21-day wearable window fills) crashes with this
`FileNotFoundError` the moment it tries to classify a scenario — visible in
`docker compose logs pulse-backend`, and the patient's `GET /status` stays stuck on `pending`
forever (the pipeline crashes before it ever writes a `SimulationRun` row, so there's nothing for
`/status` to report `running`/`failed` from).

**Fix:**

```bash
python -m src.scenario_classifier.train    # writes models/scenario_classifier.joblib + severity_regressor.joblib
docker compose up -d --build pulse-backend # rebuild so the image picks them up
```

If a patient already got stuck in `pending` from before the fix, their triggering `/wearable-sync`
call already fired and won't retry itself — push one more day's reading for that same patient
(any date past the 21-day window) to re-trigger the pipeline now that the models exist.

### General Apple Silicon note

Every Pulse-related step (`--build`'s Pulse stage, the smoke test's ~10-minute wait) is slower on
arm64 Macs because the entire `pulse-backend` container runs under Docker Desktop's amd64
emulation — `kitware/pulse:4.3.1` has no arm64 build (see `docs/methodology.md` §8). This is
expected and does not indicate anything is broken.
