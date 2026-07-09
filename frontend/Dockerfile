# Frontend image: compiles the Vite/React dashboard, then serves the static build via nginx.
#
# Build context is frontend/ itself (see docker-compose.yml's `context: ./frontend`) -- unlike
# backend/Dockerfile, this doesn't need anything from the repo root.

# ---- Stage 1: build the static bundle ----
# node:20, not 18: this project's package.json pins vite ^8.1.1, which requires Node 20.19+ or
# 22.12+ (confirmed by the actual build failure: "Vite requires Node.js version 20.19+ or
# 22.12+" / "ReferenceError: CustomEvent is not defined" under Node 18). 18-alpine was the
# originally requested base but doesn't satisfy that.
FROM node:20-alpine AS build
WORKDIR /app

# Separate dependency install from source copy so `npm ci` is cache-hit on source-only changes.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# VITE_API_URL is compiled into the static JS bundle at build time (Vite replaces
# `import.meta.env.VITE_API_URL` at build time, it is not read at container-start time) -- see
# frontend/src/api/client.js. Because the code that reads this value runs in the end user's
# browser, not inside the Docker network, it MUST be an address the browser can reach (the
# published host port), never another service's internal Compose name.
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- Stage 2: serve the build ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
