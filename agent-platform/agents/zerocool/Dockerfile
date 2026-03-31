FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    nmap \
    && rm -rf /var/lib/apt/lists/*

# Build context = raiz do projeto (agent-platform/)
COPY orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia código compartilhado do orchestrator
COPY orchestrator/ .

# Copia todos os agents
COPY agents/ /app/agents/

# Diretório de relatórios de pentest (persistido via PVC no k8s)
RUN mkdir -p /app/reports

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8005
ENV PENTEST_REPORTS_DIR=/app/reports

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8005/health || exit 1

CMD ["uvicorn", "agents.zerocool.main:app", "--host", "0.0.0.0", "--port", "8005", "--workers", "1"]
