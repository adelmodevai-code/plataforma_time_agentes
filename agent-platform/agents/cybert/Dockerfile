FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Build context = raiz do projeto (agent-platform/)
# Instala dependências do orchestrator (modelos compartilhados, etc.)
COPY orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código compartilhado do orchestrator (models, memory, messaging, storage)
COPY orchestrator/ .

# Copia todos os agents (CyberT usa dependências de outros agents via imports)
COPY agents/ /app/agents/

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8004

EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8004/health || exit 1

CMD ["uvicorn", "agents.cybert.main:app", "--host", "0.0.0.0", "--port", "8004", "--workers", "1"]
