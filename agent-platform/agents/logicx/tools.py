"""
LogicX Tools — análise, correlação e delegação ao Vops.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.observability.svc.cluster.local:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki.observability.svc.cluster.local:3100")

TOOL_DEFINITIONS = [
    {
        "name": "fetch_beholder_data",
        "description": (
            "Busca dados frescos de observabilidade: saúde do cluster, alertas ativos "
            "e métricas dos pods. Use sempre que precisar de dados atualizados antes de analisar."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "Namespace para focar (opcional)"},
                "include_logs": {"type": "boolean", "description": "Incluir logs recentes de erro (default: false)"},
            },
        },
    },
    {
        "name": "analyze_anomaly",
        "description": "Analisa uma anomalia específica com queries PromQL/LogQL direcionadas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "signal": {"type": "string", "description": "O sinal anômalo. Ex: 'CPU spike no pod gateway'"},
                "namespace": {"type": "string", "description": "Namespace afetado"},
                "promql_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Queries PromQL adicionais para investigar",
                },
                "logql_query": {"type": "string", "description": "Query LogQL para correlacionar com logs"},
            },
            "required": ["signal"],
        },
    },
    {
        "name": "correlate_signals",
        "description": "Correlaciona múltiplos sinais (métricas + logs + eventos) para identificar causa raiz.",
        "input_schema": {
            "type": "object",
            "properties": {
                "signals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de sinais a correlacionar",
                },
                "time_window": {"type": "string", "description": "Janela de correlação: '5m', '15m', '1h'"},
            },
            "required": ["signals"],
        },
    },
    {
        "name": "plan_remediation",
        "description": "Gera um plano de remediação estruturado para um problema identificado.",
        "input_schema": {
            "type": "object",
            "properties": {
                "problem": {"type": "string", "description": "Descrição do problema"},
                "root_cause": {"type": "string", "description": "Causa raiz identificada"},
                "affected_resources": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recursos afetados: pods, deployments, services",
                },
            },
            "required": ["problem", "root_cause"],
        },
    },
    {
        "name": "delegate_to_vops",
        "description": (
            "Delega uma ação de infraestrutura ao Vops. "
            "Use apenas para ações já aprovadas ou de baixo risco (scale, restart). "
            "Ações destrutivas requerem confirmação explícita do Adelmo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["scale", "restart", "rollback", "get_status", "describe"],
                    "description": "Tipo de ação",
                },
                "resource_type": {"type": "string", "description": "Tipo do recurso: deployment, statefulset, etc."},
                "resource_name": {"type": "string", "description": "Nome do recurso"},
                "namespace": {"type": "string", "description": "Namespace k8s"},
                "params": {"type": "object", "description": "Parâmetros específicos da ação (ex: replicas: 3)"},
                "reason": {"type": "string", "description": "Justificativa para a ação"},
            },
            "required": ["action", "resource_type", "resource_name", "namespace", "reason"],
        },
    },
]


async def fetch_beholder_data(namespace: str | None = None, include_logs: bool = False) -> dict:
    """Coleta dados frescos de observabilidade."""
    result: dict[str, Any] = {"timestamp": datetime.now(timezone.utc).isoformat()}

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Saúde do cluster
        health_queries = {
            "pods_running": f'count(kube_pod_status_phase{{phase="Running"{_ns(namespace)}}})',
            "pods_failed": f'count(kube_pod_status_phase{{phase="Failed"{_ns(namespace)}}})',
            "pods_crashloop": f'count(kube_pod_container_status_waiting_reason{{reason="CrashLoopBackOff"{_ns(namespace)}}})',
            "cpu_pct": "round(100 * avg(rate(container_cpu_usage_seconds_total{container!=''}[5m])) / avg(kube_node_status_capacity{resource='cpu'}))",
            "mem_pct": "round(100 * sum(container_memory_working_set_bytes{container!=''}) / sum(kube_node_status_capacity{resource='memory'}))",
        }
        metrics = {}
        for k, q in health_queries.items():
            try:
                r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q})
                series = r.json().get("data", {}).get("result", [])
                metrics[k] = series[0]["value"][1] if series else "N/A"
            except Exception:
                metrics[k] = "N/A"
        result["cluster_metrics"] = metrics

        # Alertas ativos
        try:
            r = await client.get(f"{PROMETHEUS_URL}/api/v1/alerts")
            alerts = r.json().get("data", {}).get("alerts", [])
            result["active_alerts"] = [
                {
                    "name": a["labels"].get("alertname"),
                    "severity": a["labels"].get("severity"),
                    "state": a["state"],
                }
                for a in alerts if a.get("state") == "firing"
            ]
        except Exception:
            result["active_alerts"] = []

        # Logs de erro recentes (opcional)
        if include_logs:
            ns_filter = f',namespace="{namespace}"' if namespace else ""
            query = f'{{container!=""{ns_filter}}} |= "ERROR" | line_format "{{{{.pod}}}}: {{{{__line__}}}}"'
            try:
                now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
                r = await client.get(
                    f"{LOKI_URL}/loki/api/v1/query_range",
                    params={"query": query, "limit": 20, "start": now_ns - int(15 * 60 * 1e9), "end": now_ns},
                )
                streams = r.json().get("data", {}).get("result", [])
                lines = []
                for s in streams:
                    for _, line in s.get("values", []):
                        lines.append(line[:200])
                result["recent_errors"] = lines[:20]
            except Exception:
                result["recent_errors"] = []

    return result


async def analyze_anomaly(
    signal: str,
    namespace: str | None = None,
    promql_queries: list[str] | None = None,
    logql_query: str | None = None,
) -> dict:
    """Executa queries direcionadas para análise de anomalia."""
    result: dict[str, Any] = {"signal": signal, "timestamp": datetime.now(timezone.utc).isoformat()}

    async with httpx.AsyncClient(timeout=10.0) as client:
        if promql_queries:
            metric_results = {}
            for q in promql_queries:
                try:
                    r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q})
                    series = r.json().get("data", {}).get("result", [])
                    metric_results[q] = [
                        {"labels": s["metric"], "value": s["value"][1]} for s in series[:10]
                    ]
                except Exception as e:
                    metric_results[q] = {"error": str(e)}
            result["metric_analysis"] = metric_results

        if logql_query:
            try:
                now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
                r = await client.get(
                    f"{LOKI_URL}/loki/api/v1/query_range",
                    params={
                        "query": logql_query,
                        "limit": 30,
                        "start": now_ns - int(30 * 60 * 1e9),
                        "end": now_ns,
                    },
                )
                streams = r.json().get("data", {}).get("result", [])
                lines = []
                for s in streams:
                    for ts, line in s.get("values", []):
                        lines.append({
                            "time": datetime.fromtimestamp(int(ts)/1e9, tz=timezone.utc).isoformat(),
                            "log": line[:300],
                        })
                result["log_evidence"] = lines[:30]
            except Exception as e:
                result["log_evidence"] = {"error": str(e)}

    return result


async def correlate_signals(signals: list[str], time_window: str = "15m") -> dict:
    """Estrutura dados para correlação — LogicX usa seu raciocínio para correlacionar."""
    return {
        "signals_to_correlate": signals,
        "time_window": time_window,
        "instruction": (
            "Analise os sinais acima considerando: "
            "1) Qual veio primeiro? 2) Há relação causal? "
            "3) Qual o impacto no SLO? Use os dados do fetch_beholder_data para validar."
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def plan_remediation(
    problem: str,
    root_cause: str,
    affected_resources: list[str] | None = None,
) -> dict:
    """Gera estrutura de plano de remediação."""
    return {
        "problem": problem,
        "root_cause": root_cause,
        "affected_resources": affected_resources or [],
        "plan_template": {
            "immediate": "Ações para estabilizar (< 5 min)",
            "short_term": "Ações para resolver a causa raiz (< 1h)",
            "preventive": "Ações para evitar recorrência",
            "rollback": "Como desfazer se a remediação piorar",
        },
        "requires_vops": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def delegate_to_vops(
    action: str,
    resource_type: str,
    resource_name: str,
    namespace: str,
    reason: str,
    params: dict | None = None,
) -> dict:
    """Prepara delegação ao Vops — retorna payload estruturado."""
    return {
        "delegation": {
            "to": "Vops",
            "action": action,
            "resource_type": resource_type,
            "resource_name": resource_name,
            "namespace": namespace,
            "params": params or {},
            "reason": reason,
            "requested_by": "LogicX",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
        "status": "pending_vops_execution",
        "message": f"Vops receberá a solicitação: {action} {resource_type}/{resource_name} em {namespace}",
    }


async def execute_tool(tool_name: str, tool_input: dict) -> Any:
    dispatch = {
        "fetch_beholder_data": lambda i: fetch_beholder_data(i.get("namespace"), i.get("include_logs", False)),
        "analyze_anomaly": lambda i: analyze_anomaly(i["signal"], i.get("namespace"), i.get("promql_queries"), i.get("logql_query")),
        "correlate_signals": lambda i: correlate_signals(i["signals"], i.get("time_window", "15m")),
        "plan_remediation": lambda i: plan_remediation(i["problem"], i["root_cause"], i.get("affected_resources")),
        "delegate_to_vops": lambda i: delegate_to_vops(i["action"], i["resource_type"], i["resource_name"], i["namespace"], i["reason"], i.get("params")),
    }
    fn = dispatch.get(tool_name)
    return await fn(tool_input) if fn else {"error": f"Tool desconhecida: {tool_name}"}


def _ns(namespace: str | None) -> str:
    return f',namespace="{namespace}"' if namespace else ""
