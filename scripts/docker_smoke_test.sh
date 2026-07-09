#!/usr/bin/env bash
# Manual smoke test for the docker-compose stack (Phase 9): creates one real patient, feeds it a
# full 21-day wearable window via the live API, and polls until the real (non-mocked) Pulse-driven
# background pipeline completes. Confirms the Pulse binary actually executes inside the
# pulse-backend container -- the one thing that couldn't be verified without a running daemon.
#
# Prerequisite: `docker compose up` (or `up --build`) already running in another terminal.
# Run with: bash scripts/docker_smoke_test.sh
set -euo pipefail

BASE=http://localhost:8000

echo "Creating patient..."
PID=$(curl -s -X POST "$BASE/patients" -H "Content-Type: application/json" \
  -d '{"age":65,"sex":"Male","height_cm":175,"weight_kg":80}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "Created patient: $PID"

curl -s -X POST "$BASE/patients/$PID/clinical-report" -H "Content-Type: application/json" \
  -d '{"ejection_fraction_pct":35,"nt_probnp_pg_ml":1200}' > /dev/null
echo "Clinical report submitted."

echo "Syncing 21 days of wearable data..."
for i in $(seq 0 20); do
  DATE=$(date -v +"${i}"d +%Y-%m-%d)
  curl -s -X POST "$BASE/patients/$PID/wearable-sync" -H "Content-Type: application/json" \
    -d "{\"recorded_date\":\"$DATE\",\"resting_hr_bpm\":75,\"spo2_pct\":95,\"weight_kg\":81,\"steps_per_day\":4000,\"sleep_hours\":6,\"hrv_rmssd_ms\":30}" > /dev/null
done
echo "21 days synced -- background Pulse pipeline should now be running (up to ~10 min under emulation)."

echo "Polling /status every 15s (up to 15 min)..."
for i in $(seq 1 60); do
  STATUS=$(curl -s "$BASE/patients/$PID/status" | python3 -c "import sys,json;print(json.load(sys.stdin)['simulation_status'])")
  echo "[$i] status: $STATUS"
  if [ "$STATUS" = "complete" ] || [ "$STATUS" = "failed" ]; then
    break
  fi
  sleep 15
done

echo ""
echo "Final report:"
curl -s "$BASE/patients/$PID/report" | python3 -m json.tool
