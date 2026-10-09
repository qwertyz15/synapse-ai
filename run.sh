#!/usr/bin/env bash
# Start the agent service and the web UI together; Ctrl+C (or either one exiting) stops everything.
# Usage: ./run.sh [--ingest] [--streamlit]
#   --ingest     index ./data for document search before starting
#   --streamlit  also start the legacy Streamlit app on :8501
set -euo pipefail

cd "$(dirname "$0")"

PORT="${PORT:-8080}"
WEB_PORT="${WEB_PORT:-3000}"
INGEST=false
STREAMLIT=false
for arg in "$@"; do
    case "$arg" in
        --ingest) INGEST=true ;;
        --streamlit) STREAMLIT=true ;;
        *) echo "Unknown option: $arg" >&2; exit 2 ;;
    esac
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
