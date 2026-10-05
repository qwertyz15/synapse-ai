#!/usr/bin/env bash
# Create a brand-new git history for a copy of this project, as 21 logical commits.
#
# Usage (in a COPY of the project whose .git folder you deleted):
#   ./commit-scratch.sh            # git init + 21 commits on branch main
#   ./commit-scratch.sh trunk      # same, on a branch named trunk
#
# Files are taken from the folder itself; anything .gitignore excludes (node_modules, .next,
# .env, chroma_db, databases...) is left out, except FORCE_INCLUDE. Every remaining file lands
# in exactly one commit: the run aborts if a file matches no group, and verifies at the end
# that nothing was left uncommitted. Nothing is pushed.
# Commits hold final file versions grouped by feature, so early commits show the project's
# structure but aren't guaranteed to build on their own.
set -euo pipefail

cd "$(dirname "$0")"
SELF="$(basename "$0")"
BRANCH="${1:-main}"
TOTAL=21

# Tracked in the original repo even though .gitignore matches them.
FORCE_INCLUDE=(data/AcmeTech_Employee_Handbook.pdf)

if [[ -e .git ]]; then
    echo "This folder already has a .git. Run this in a copy of the project with .git deleted." >&2
    exit 1
fi
if [[ -z "$(git config user.name || true)" || -z "$(git config user.email || true)" ]]; then
    echo 'Set your identity first: git config --global user.name "..." && git config --global user.email "..."' >&2
    exit 1
fi

# Ordered rules: the first matching pattern decides a file's commit, so specific paths
# come before the directories that contain them.
group_for() {
    case "$1" in
        .gitignore | .dockerignore | .env.example | .pre-commit-config.yaml | pyproject.toml | uv.lock | \
            codecov.yml | langgraph.json | CLAUDE.md | privatecredentials/*)
            echo 1 ;;

        src/core/embeddings.py | tests/core/test_embeddings.py) echo 9 ;;
        src/core/* | src/schema/* | tests/core/* | tests/schema/* | tests/conftest.py) echo 2 ;;

        src/agents/__init__.py | src/agents/agents.py | src/agents/lazy_agent.py | src/agents/utils.py | \
            src/agents/chatbot.py | tests/agents/test_agent_loading.py | tests/agents/test_lazy_agent.py)
            echo 3 ;;

        src/service/threads.py | src/memory/* | tests/service/test_threads.py | tests/service/test_threads_sqlite.py | \
            tests/smoke/* | src/db/* | alembic.ini | tests/service/test_app_database.py)
            echo 5 ;;
        src/service/rag.py | tests/service/test_rag_documents.py) echo 10 ;;
        src/service/agui.py | tests/service/test_agui.py | docs/AGUI.md | scripts/agui-client/*) echo 20 ;;
        tests/service/test_rag_attachments.py | tests/service/test_delete_thread.py) echo 19 ;;
        src/service/* | src/run_service.py | src/run_agent.py | tests/service/*) echo 4 ;;

        tests/app/test_documents_page.py | src/pages/*) echo 10 ;;
        src/client/* | src/run_client.py | src/streamlit_app.py | src/voice/* | tests/client/* | tests/app/* | \
            tests/voice/*)
            echo 6 ;;

        src/agents/research_assistant.py | src/agents/safeguard.py | src/agents/tools.py | \
            tests/agents/test_research_assistant.py)
            echo 7 ;;
        src/agents/bg_task_agent/* | src/agents/command_agent.py | src/agents/interrupt_agent.py | \
            src/agents/knowledge_base_agent.py | src/agents/langgraph_supervisor_agent.py | \
            src/agents/langgraph_supervisor_hierarchy_agent.py)
            echo 8 ;;

        src/ingestion/attachments.py) echo 19 ;;
        src/ingestion/* | scripts/ingest.py | tests/ingestion/* | data/*) echo 9 ;;
        src/agents/rag_assistant.py | docs/RAG_Assistant.md) echo 10 ;;

        docker/Dockerfile.web) echo 15 ;;
        docker/* | compose.yaml | run.sh | tests/integration/* | docs/File_Based_Credentials.md) echo 11 ;;

        src/agents/github_mcp_agent/* | tests/agents/test_github_mcp_agent.py | \
            tests/agents/test_github_context_persistence.py | docs/GitHub_MCP_Agent.md)
            echo 16 ;;
        frontend/app/api/github/* | frontend/lib/server/* | frontend/components/github-connect.tsx) echo 17 ;;
        src/agents/github_tools.py | tests/agents/test_github_tools.py | \
            tests/agents/test_research_assistant_connectors.py | frontend/components/chat/use-chat-connectors.ts | \
            frontend/app/api/agent/__tests__/*)
            echo 18 ;;
        frontend/components/chat/attach-menu.tsx | frontend/components/chat/use-chat-attachments.ts) echo 19 ;;

        frontend/app/api/agent/* | frontend/proxy.ts | frontend/lib/__tests__/* | frontend/lib/api.ts | \
            frontend/lib/sse.ts | frontend/lib/types.ts | frontend/lib/constants.ts | frontend/lib/chat-reducer.ts | \
            frontend/lib/agents.ts)
            echo 13 ;;
        frontend/components/chat/* | frontend/components/app-provider.tsx | frontend/components/icon-button.tsx | \
            frontend/components/service-error.tsx | frontend/app/layout.tsx | frontend/app/page.tsx | \
            frontend/app/chat/*)
            echo 14 ;;
        frontend/components/sidebar/* | frontend/app/library/*) echo 15 ;;
        frontend/*) echo 12 ;;

        scripts/* | docs/* | media/* | README.md) echo 21 ;;
        *) echo "" ;;
    esac
}

MESSAGES=(
    ""
    "chore: project setup

uv-managed Python project with lint, type-check and pre-commit configuration,
environment template and LangGraph Studio config."
    "feat: core settings, model catalog and schemas

Pydantic settings, the supported model catalog with get_model(), and the
API schemas shared by the service and clients."
    "feat: agent registry with a simple chatbot

Registry and lazy-loading base for agents, plus a minimal chatbot."
    "feat: FastAPI agent service

Invoke and SSE streaming endpoints, history, feedback, bearer auth and the
service entry point."
    "feat: conversation memory and the app database

SQLite, Postgres and MongoDB checkpointers for conversations, and a SQLAlchemy
app database with Alembic migrations for chats, attachments and the library
index, filled from existing checkpoints on first start."
    "feat: Python client, Streamlit app and voice

AgentClient for the service API, the Streamlit chat app, and optional
speech-to-text / text-to-speech."
    "feat: research assistant with tools

Web search, calculator, weather and a safety guard around the model."
    "feat: demo agents

Supervisor and hierarchical supervisor, background task, interrupt, command
and Bedrock knowledge base agents."
    "feat: incremental document ingestion

Parsers, cleaning, chunking and a Chroma index with a manifest so only
changed files are re-embedded; OpenAI or Voyage embeddings; ingest script
and sample handbook."
    "feat: document library endpoints and RAG assistant

Upload, list and delete library documents through the service, the
DocumentSearch tool, the RAG assistant and the Streamlit documents page."
    "feat: Docker setup and run script

Service and Streamlit images, compose stack with Postgres, optional MongoDB,
run.sh to start everything locally, and file-based credentials."
    "chore(web): scaffold Next.js app with Tailwind and shadcn/ui

Next.js, TypeScript, Tailwind CSS and shadcn/ui components, lint, format
and test configuration, theme tokens and app icon."
    "feat(web): agent API proxy and streaming core

Server-side proxy that adds the service token and an anonymous per-browser
user id, the SSE parser and the chat reducer, with tests on recorded streams."
    "feat(web): chat interface

Streaming chat with Markdown, code blocks, citation chips, tool steps,
sub-agent and task cards, composer, stop, retry and feedback."
    "feat(web): sidebar history and Library page

Conversations grouped by date with search, theme menu, mobile drawer, the
Library page for documents, and the web UI Docker image."
    "feat: per-user GitHub token for the GitHub MCP agent

The token travels as LangGraph run context and an MCP tool interceptor adds
it to each call, so it is never written to checkpoints or traces."
    "feat(web): Connect GitHub with OAuth

GitHub App OAuth with state and PKCE, an encrypted session cookie, token
refresh, install-step chaining and disconnect."
    "feat: GitHub connector in the research assistant

Shared GitHub MCP tools limited to core toolsets and read-only by default,
turned on per chat from the composer's + menu."
    "feat: chat attachments and chat deletion

Files attached to one chat are indexed in their own Chroma collection and
searched with the library; deleting a chat removes its messages and files."
    "feat: AG-UI protocol endpoint

AG-UI run endpoints for the agents, with a small JavaScript test client."
    "docs: guides, smoke tests and README

Deployment and provider guides, smoke and e2e scripts, media and the README."
)

git init -q -b "$BRANCH"

mapfile -d '' -t FOUND < <(git ls-files -z --others --exclude-standard)
FILES=()
for f in "${FOUND[@]}"; do
    [[ "$f" == "$SELF" ]] || FILES+=("$f")
done
for f in "${FORCE_INCLUDE[@]}"; do
    [[ -f "$f" ]] && FILES+=("$f")
done

declare -A GROUP
unassigned=()
for f in "${FILES[@]}"; do
    g="$(group_for "$f")"
    if [[ -z "$g" ]]; then unassigned+=("$f"); else GROUP["$f"]="$g"; fi
done
if ((${#unassigned[@]})); then
    printf 'No commit group for these files (add a rule in group_for):\n' >&2
    printf '  %s\n' "${unassigned[@]}" >&2
    rm -rf .git
    exit 1
fi

made=0
for i in $(seq 1 "$TOTAL"); do
    batch=()
    for f in "${FILES[@]}"; do
        [[ "${GROUP[$f]}" == "$i" ]] && batch+=("$f")
    done
    if ((${#batch[@]} == 0)); then
        echo "skipped (no files): $(head -1 <<<"${MESSAGES[$i]}")"
        continue
    fi
    printf '%s\0' "${batch[@]}" | git add --force --pathspec-from-file=- --pathspec-file-nul
    git commit -q -m "${MESSAGES[$i]}"
    made=$((made + 1))
    printf '%2d. %s  %-58s %3d files\n' "$made" "$(git rev-parse --short HEAD)" "$(head -1 <<<"${MESSAGES[$i]}")" "${#batch[@]}"
done

leftover="$(git ls-files --others --exclude-standard | grep -vxF "$SELF" || true)"
if [[ -n "$leftover" ]]; then
    echo "Some files were not committed:" >&2
    echo "$leftover" >&2
    exit 1
fi

echo
echo "Done: $made commits, $(git ls-files | wc -l) files on branch $BRANCH. Nothing was pushed."
echo "Not committed (ignored by .gitignore): .env, node_modules, .next, chroma_db, databases and similar."
