# Backend image for the M2K HF-PULSE FastAPI service, with the Pulse physiology engine baked in.
#
# Build context is the REPO ROOT, not this directory (see docker-compose.yml's
# `context: .` / `dockerfile: backend/Dockerfile`) -- the app needs src/, models/, and
# data/synthetic/ from the repo root, not just this backend/ folder.
#
# IMPORTANT: both stages are pinned to linux/amd64. kitware/pulse:4.3.1 only ships an amd64
# image (see docs/methodology.md §8's arm64->amd64 emulation note) -- PulseScenarioDriver is a
# compiled binary with no arm64 build. If the final stage below were left to build natively as
# arm64 on Apple Silicon, the copied-in Pulse binary simply could not execute (you cannot mix
# instruction sets inside one running container). Pinning --platform=linux/amd64 on every stage
# makes Docker Desktop's emulation layer apply to the whole image consistently, the same way the
# project's existing `docker run ... kitware/pulse:4.3.1` invocations already work -- slower on
# Apple Silicon, but correct. This is also set on the pulse-backend service in docker-compose.yml
# as a second layer of insurance.

# ---- Stage 1: extract the Pulse engine (binary + its data/state files) ----
FROM --platform=linux/amd64 kitware/pulse:4.3.1 AS pulse-source
# Copies the whole /pulse tree, not just bin/PulseScenarioDriver: the engine's own patient
# templates (StandardMale.json etc.), environment files, and stabilized engine states live
# alongside the binary and src/patient_builder + src/pulse_runner reference them relatively --
# see docs/methodology.md §4/§7. Copying only the executable would leave those unresolved.

# ---- Stage 2: the actual backend image ----
FROM --platform=linux/amd64 python:3.11-slim

# PulseScenarioDriver is a compiled C++ binary; python:3.11-slim strips most non-Python system
# libraries by default. Confirmed via `docker compose exec pulse-backend ldd
# /pulse/bin/PulseScenarioDriver` against a real build: it needs libc++/libc++abi (Pulse was
# built against LLVM's C++ runtime, not GCC's -- libstdc++6/libgomp1 below turned out to be
# unnecessary for this specific binary but are harmless to keep in case another binary under
# /pulse/bin needs them). Every other dependency (libpthread, librt, libm, libgcc_s, libc)
# already resolved against python:3.11-slim's base libc, confirmed by that same ldd run.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libc++1 \
    libc++abi1 \
    libstdc++6 \
    libgomp1 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=pulse-source /pulse /pulse

# WORKDIR is /workspace, not /app -- src/api/services.py hardcodes
# SCENARIOS_DIR = pathlib.Path("/workspace/scenarios/api"), and src/pulse_runner/runner.py's
# run_pulse() is invoked with scenario paths built relative to this same convention (matching
# every `docker run -v "$(pwd)":/workspace -w /workspace ...` invocation documented in the
# README). Changing this would require touching application code, not just this Dockerfile.
WORKDIR /workspace

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copies the whole repo context (filtered by .dockerignore) rather than an explicit file list --
# simplest way to guarantee src/, models/*.joblib (already trained locally per the project's own
# convention -- see README's "Train the Phase 3 scenario classifier" section), and
# data/synthetic/*.csv + reference_stats.yaml are all present, without maintaining a second,
# easily-stale list of "files the API needs" here.
COPY . .

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
