#!/usr/bin/env bash
# Run Synapse locally (agent service + web UI), or manage the Docker setup. See ./run.sh --help.
set -euo pipefail

cd "$(dirname "$0")"

usage() {
    cat <<'USAGE'
Usage: ./run.sh [options]            run locally: agent service + web UI (Ctrl+C stops both)
       ./run.sh --docker <command>   manage the Docker setup instead

Local options:
  --ingest       index the files in ./data into the shared library before starting
  --streamlit    also start the legacy Streamlit app on :8501
  -h, --help     show this help
  Ports: PORT (agent service, default 8080) and WEB_PORT (web UI, default 3000),
  e.g. PORT=8090 WEB_PORT=3001 ./run.sh

Docker commands:
  up             build and start everything in the background (http://localhost:3000)
  down           stop everything (data stays in Docker volumes)
  restart [svc]  restart all services, or one (e.g. worker)
  logs [svc]     follow logs, of everything or one service (e.g. worker, agent_service)
  ps             show the status of each service
  build          rebuild the images
  watch          development mode: rebuild or sync services when code changes

Background worker without Docker (needs REDIS_URL and QDRANT_URL in .env):
  cd src && uv run celery -A worker worker -Q ingestion

More commands: make help (if make is installed). Setup guide: README.md, "Getting started".
USAGE
}

docker_command() {
    command -v docker >/dev/null || { echo "Docker is required for --docker." >&2; exit 1; }
    local cmd="${1:-}"
    shift || true
    case "$cmd" in
        up) docker compose up -d --build --wait && echo "Synapse is running: http://localhost:3000" ;;
        down) docker compose down ;;
        restart) docker compose restart "$@" ;;
        logs) docker compose logs -f --tail=100 "$@" ;;
        ps) docker compose ps ;;
        build) docker compose build "$@" ;;
        watch) docker compose watch ;;
        *) echo "Unknown or missing Docker command: '$cmd'" >&2; echo >&2; usage >&2; exit 2 ;;
    esac
}

PORT="${PORT:-8080}"
WEB_PORT="${WEB_PORT:-3000}"
INGEST=false
STREAMLIT=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h | --help) usage; exit 0 ;;
        --docker) shift; docker_command "$@"; exit $? ;;
        --ingest) INGEST=true ;;
        --streamlit) STREAMLIT=true ;;
        *) echo "Unknown option: $1 (see ./run.sh --help)" >&2; exit 2 ;;
    esac
    shift
done

command -v npm >/dev/null || { echo "Node.js (npm) is required for the web UI." >&2; exit 1; }

uv sync --frozen
if [[ ! -d frontend/node_modules || frontend/package-lock.json -nt frontend/node_modules ]]; then
    (cd frontend && npm ci)
fi

if $INGEST; then
    uv run python scripts/ingest.py
fi

trap 'trap - INT TERM EXIT; kill 0 2>/dev/null; wait 2>/dev/null' INT TERM EXIT

uv run python src/run_service.py &
SERVICE_PID=$!

echo "Waiting for the service on port $PORT..."
until curl -sf "http://localhost:$PORT/health" >/dev/null; do
    if ! kill -0 "$SERVICE_PID" 2>/dev/null; then
        echo "Service failed to start." >&2
        exit 1
    fi
    sleep 1
done

env_value() {
    local value
    value="$(grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- || true)"
    value="${value%[\"\']}"
    printf '%s' "${value#[\"\']}"
}

(
    cd frontend
    export AGENT_URL="http://localhost:$PORT"
    for key in AUTH_SECRET GITHUB_CLIENT_ID GITHUB_CLIENT_SECRET GITHUB_APP_SLUG WEB_SESSION_SECRET \
        AUTH_ENABLED GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET GOOGLE_REDIRECT_URI \
        RATE_LIMIT_CHATS_PER_HOUR RATE_LIMIT_CHATS_PER_MINUTE_GLOBAL RATE_LIMIT_UPLOADS_PER_HOUR; do
        export "$key=$(cd .. && env_value "$key")"
    done
    npm run dev -- --port "$WEB_PORT"
) &

if $STREAMLIT; then
    uv run streamlit run src/streamlit_app.py --server.headless true &
    echo "Streamlit app: http://localhost:8501"
fi

echo "Open http://localhost:$WEB_PORT"
wait -n
echo "A process exited; shutting down." >&2
