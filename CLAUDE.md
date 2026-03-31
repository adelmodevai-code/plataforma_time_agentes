# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Chat_Time_Agentes** is a multi-agent orchestration platform where specialized agents handle different domains autonomously. The system uses intelligent routing, vector memory, and agent delegation to solve complex problems.

### Core Components

1. **Orchestrator** (Python/FastAPI at `agent-platform/orchestrator/`)
   - Central message router with keyword-based agent selection
   - Manages conversation history (Redis) and vector memory (Qdrant)
   - Supports agent delegation (e.g., LogicX → Vops)
   - FastAPI with SSE streaming to Gateway

2. **Gateway** (Go at `agent-platform/gateway/`)
   - HTTP entry point, translates client requests to orchestrator
   - Ports: 8080 → orchestrator:8001

3. **Web UI** (React/TypeScript/Vite at `agent-platform/web/`)
   - Frontend interface, connects to Gateway via HTTP
   - Markdown rendering for agent responses
   - Port: 3000

4. **Infrastructure**
   - **Redis** (port 6379): Conversation history, session state
   - **NATS** (port 4222): Event messaging for agent orchestration
   - **Qdrant** (port 6333): Vector database for long-term memory

### Six Agents

| Agent | Purpose | Trigger Keywords | Phase |
|-------|---------|------------------|-------|
| **Beholder** | Default entry point, observability sentinel | Generic requests | 1 |
| **Metatron** | Documentation, reporting, file generation | "documentar", "registre", "relatório", "ata", "arquivo" | 1 |
| **LogicX** | Analysis, root cause, incident correlation | "analise", "causa raiz", "diagnóstico" | 3+ |
| **Vops** | Kubernetes operations | "deploy", "scale", "pod", "kubectl" | 3+ |
| **CyberT** | Security auditing, vulnerability scanning | "vulnerabilidade", "cve", "segurança" | 4 |
| **Zerocool** | Authorized penetration testing (requires approval) | "pentest", "confirmar vulnerabilidade" | 4 |

---

## Common Development Tasks

### Start Full Stack (Docker Compose)

```bash
# Build and start all services
cd agent-platform
docker-compose up -d

# Check status
docker-compose ps

# Stop everything
docker-compose down

# View logs
docker-compose logs orchestrator -f
docker-compose logs gateway -f
docker-compose logs web -f
```

Services health check endpoints:
- **Orchestrator**: `http://localhost:8001/health`
- **Gateway**: Checks orchestrator health
- **Web UI**: `http://localhost:3000`

Dashboard URLs:
- **Qdrant Dashboard**: `http://localhost:6333/dashboard`
- **NATS Monitoring**: `http://localhost:8222`

### Orchestrator (Python)

```bash
cd agent-platform/orchestrator

# Install dependencies
pip install -r requirements.txt

# Run locally (development mode)
ENV=development ANTHROPIC_API_KEY=<your-key> python main.py

# Run tests (if available)
pytest

# Format code
black .
isort .

# Lint
ruff check .
```

**Key files:**
- `main.py` — FastAPI app, lifespan hooks, endpoints
- `router/agent_router.py` — Message routing logic, agent selection, delegation
- `models/messages.py` — Pydantic models (InboundRequest, StreamEvent, AgentName, etc.)
- `memory/redis_client.py` — Conversation history, approval state
- `memory/qdrant_memory.py` — Vector storage, semantic search
- `messaging/nats_bus.py` — Event publishing, topics
- `agents/` — Agent implementations (lazy-loaded in router)

### Gateway (Go)

```bash
cd agent-platform/gateway

# Build
go build -o gateway ./cmd/main.go

# Run
PORT=8080 ORCHESTRATOR_URL=http://localhost:8001 ./gateway

# Format
go fmt ./...

# Lint
golangci-lint run
```

### Web UI (React/TypeScript)

```bash
cd agent-platform/web

# Install dependencies
npm install

# Development server
npm run dev
# Opens at http://localhost:5173

# Build for production
npm run build

# Preview production build
npm run preview

# Lint
npm run lint
```

**Key directories:**
- `src/components/` — React components
- `src/pages/` — Page-level components
- `src/api/` — HTTP client for Gateway

---

## Architecture Patterns

### Agent Routing (agent_router.py)

```
User Message
    ↓
[1] Extract keywords → Select agent (Metatron, LogicX, Vops, CyberT, Zerocool, or default Beholder)
    ↓
[2] Search vector memory (Qdrant) for relevant past interactions
    ↓
[3] Load conversation history from Redis
    ↓
[4] Inject memories into request as context
    ↓
[5] Execute agent with streaming → yield events (MESSAGE, ACTION, COMPLETE, DELEGATION, ERROR)
    ↓
[6] Store conversation + response in both Redis and Qdrant
    ↓
[7] Handle delegation: if agent delegates to another (e.g., LogicX → Vops),
    chain within same SSE stream
```

### Memory System

- **Redis**: Session-scoped. Stores conversation messages with role (user/assistant) and metadata (agent, timestamp).
- **Qdrant**: Long-term indexed. Stores all exchanges (user queries + agent responses) with metadata (agent name, session_id, timestamp). Enables semantic search: `vector_memory.search(query=..., agent=..., top_k=5, score_threshold=0.60)`.

### Agent Lifecycle

1. **Lazy import** in router's `_get_agent(name)` — agents only loaded when needed
2. **Async generator** — agents yield StreamEvent objects (MESSAGE, ACTION, COMPLETE, ERROR, etc.)
3. **Streaming to UI** — SSE chunks real-time output

### Delegation Flow

When an agent (e.g., LogicX) yields `EventType.DELEGATION`:
1. Router publishes event to NATS (observability)
2. Constructs InboundRequest for target agent (e.g., Vops)
3. Executes target within same SSE stream
4. Both responses stored in memory

### NATS Topics (`orchestrator/messaging/topics.py`)

| Topic | Published by | Subscribed by | Payload key fields |
|-------|-------------|---------------|--------------------|
| `agents.delegate` | LogicX, CyberT | Orchestrator | `to`, `action`, `reason` |
| `agents.beholder.alert` | Beholder (poller + tool) | All agents | `alert_name`, `severity`, `summary`, `labels`, `source`, `session_id` |
| `agents.metatron.archive` | Zerocool, LogicX, Vops | Metatron (planned) | — |
| `agents.vops.result` | Vops | LogicX, Orchestrator | — |
| `agents.session.event` | Orchestrator | Observability | — |

### Beholder Alert Broadcast

Two alert paths exist:

**Proactive (background)** — `orchestrator/messaging/alert_broadcaster.py`:
- Singleton `alert_broadcaster` polls `list_active_alerts` every `ALERT_POLL_INTERVAL` seconds (default: 60)
- Deduplication via SHA-256 fingerprint of `(alertname, labels)` — same alert not re-published while still firing
- Started in `main.py` lifespan after NATS connects; `stop()` clears state on shutdown
- Degrades gracefully: if Prometheus is offline, logs and skips the cycle

**Reactive (tool use)** — `publish_alert` tool in `agents/beholder/tools.py`:
- Claude calls this tool during a conversation when it detects a critical anomaly
- Publishes to `agents.beholder.alert` with `source: "beholder-agent"` and the active `session_id`

---

## Message Models

All defined in `orchestrator/models/messages.py`:

```python
# Incoming request
InboundRequest:
  - session_id: str (UUID, conversation identifier)
  - message_id: str (unique per message)
  - content: str (user message)
  - type: MessageType (MESSAGE, APPROVAL, DENIAL)
  - metadata: dict (optional context)

# Streaming event
StreamEvent:
  - agent: AgentName (BEHOLDER, METATRON, LOGICX, VOPS, CYBERT, ZEROCOOL, SYSTEM)
  - type: EventType (MESSAGE, ACTION, COMPLETE, ERROR, DELEGATION)
  - content: str (streamed text)
  - metadata: dict (for DELEGATION: to, action, resource_type, resource_name, params, reason)
  - timestamp: str (ISO 8601)

# History
ConversationMessage:
  - role: str ("user" or "assistant")
  - content: str
  - agent: AgentName (only for assistant)
```

---

## Agent Implementation Pattern

Each agent (e.g., `agents/beholder/agent.py`):

```python
class BeholderAgent:
    async def run(self, request: InboundRequest, history: list) -> AsyncIterator[StreamEvent]:
        """
        Yields StreamEvents as response streams in.
        - REQUEST: Always receives InboundRequest + conversation history
        - YIELDS: MESSAGE (chunks), ACTION (operations), COMPLETE, ERROR, DELEGATION (to delegate to another agent)
        - MEMORY: Qdrant memories already injected in request.content if relevant
        """
        # [1] Load memories (already in request if injected by router)
        # [2] Build prompt with history + current request
        # [3] Stream from Claude with Anthropic SDK
        # [4] Yield MESSAGE events as tokens arrive
        # [5] Optionally yield DELEGATION if delegating
        # [6] Yield COMPLETE when done
```

Key: Agents assume memories are already in the request if relevant. Router injects them before calling agent.

### Metatron File Tools

Metatron has file generation capabilities via `agents/metatron/tools.py`:

| Tool | Description |
|------|-------------|
| `write_file` | Creates/overwrites `.md`, `.txt`, `.json` files |
| `create_report` | Generates structured markdown report with header, sections, tags |
| `append_to_file` | Appends content to an existing file |
| `list_files` | Lists all files generated in the current session |
| `read_file` | Reads content of an existing session file |

Files are managed by `storage/file_storage.py` (FileStorage / FileMetadata). Each file gets a `download_url` served by the orchestrator. Scope: per `session_id`.

---

## Key Environment Variables

```bash
# Orchestrator
ANTHROPIC_API_KEY=sk-...                    # Required
CLAUDE_MODEL=claude-sonnet-4-6              # Default
REDIS_URL=redis://localhost:6379            # Or redis://redis:6379 in Docker
NATS_URL=nats://localhost:4222              # Or nats://nats:4222 in Docker
QDRANT_URL=http://localhost:6333            # Or http://qdrant:6333 in Docker
PORT=8001                                   # Orchestrator port
ENV=development                             # Or 'production'
PROMETHEUS_URL=http://localhost:30090       # Optional observability
LOKI_URL=http://localhost:3100              # Optional observability
ALERT_POLL_INTERVAL=60                      # Beholder alert poller interval (seconds, default: 60)

# Gateway
PORT=8080
ORCHESTRATOR_URL=http://localhost:8001      # Or http://orchestrator:8001 in Docker

# .env file (orchestrator/):
ANTHROPIC_API_KEY=sk-...
CLAUDE_MODEL=claude-sonnet-4-6
```

---

## Testing & Quality

### Python (Orchestrator)

```bash
# Run tests
pytest

# With coverage
pytest --cov=. --cov-report=html

# Single test
pytest tests/test_agent_router.py::test_agent_selection

# Lint & format
black .
isort .
ruff check . --fix
```

### TypeScript (Web UI)

```bash
# Type checking
tsc --noEmit

# Lint
npm run lint

# Format (if prettier configured)
npm run format
```

---

## Debugging

### Orchestrator Logs

```bash
# Local
ENV=development python main.py

# Docker
docker-compose logs -f orchestrator

# Check structured logs (structlog output)
# Look for: session_id, agent names, event types
```

### Vector Memory Debug

```python
# In Python REPL or test
from memory.qdrant_memory import vector_memory
await vector_memory.connect()
info = await vector_memory.collection_info()
print(info)
```

### Agent Status

```bash
curl http://localhost:8001/agents/status
curl http://localhost:8001/memory/stats
```

---

## Code Organization Notes

- **Max file size**: 400-600 lines. Split agents and utilities into separate modules.
- **No deep nesting**: Extract helper functions if >4 levels deep.
- **Immutability**: Use `@dataclass(frozen=True)` or `NamedTuple` for DTOs.
- **Async patterns**: Use `AsyncIterator` for streams, `asyncio.create_task()` for fire-and-forget.
- **Error handling**: Catch at boundaries (network, user input), propagate with context.
- **No hardcoded secrets**: Use `.env` and `os.getenv()` with required checks.

---

## Git & Commits

- **Branch**: Develop on feature branches, PR to `master`
- **Commit format**: `<type>: <description>` (feat, fix, refactor, docs, test, chore)
- **Example**: `feat: add agent delegation to Vops for k8s operations`

---

## Phase Roadmap

- **Phase 1**: Beholder (entry) + Metatron (docs + file tools) ✅ COMPLETE
- **Phase 2**: Observability (Prometheus, Loki) + Beholder NATS broadcast ✅ COMPLETE
- **Phase 3**: LogicX + Vops (analysis + operations)
- **Phase 4**: CyberT + Zerocool (security)

### Next Steps (priority order)

1. **Zerocool → Metatron via NATS** ← NEXT — After pentest, Zerocool publishes to `agents.metatron.archive`; Metatron subscribes and auto-archives the report (both dependencies ready ✅)
2. **K8s microservices — Option B** — Independent pods for CyberT and Zerocool (can be done independently)

Later phases introduce complexity; early phases focus on core routing and memory.
