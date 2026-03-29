"""
Beholder Tools — integração real com Prometheus, Loki e Kubernetes.
Cada função é uma ferramenta que o agente Beholder pode chamar via Claude tool use.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

log = structlog.get_logger(__name__)

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.observability.svc.cluster.local:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki.observability.svc.cluster.local:3100")
HTTP_TIMEOUT = 10.0


# ─── Definições de tools para a Claude API ───────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "query_prometheus",
        "description": (
            "Executa uma query PromQL no Prometheus e retorna os resultados. "
            "Use para obter métricas do cluster k8s: CPU, memória, rede, pods, etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query PromQL. Ex: 'up', 'rate(container_cpu_usage_seconds_total[5m])'",
                },
                "time_range": {
                    "type": "string",
                    "description": "Período para range queries: '5m', '1h', '24h'. Omitir para instant query.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_loki",
        "description": (
            "Consulta logs no Loki usando LogQL. "
            "Use para buscar erros, eventos ou padrões nos logs dos pods."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query LogQL. Ex: '{namespace=\"agent-platform\"} |= \"ERROR\"'",
                },
                "limit": {
                    "type": "integer",
                    "description": "Número máximo de linhas retornadas (default: 50)",
                    "default": 50,
                },
                "since": {
                    "type": "string",
                    "description": "Janela de tempo para busca: '5m', '1h', '24h' (default: '1h')",
                    "default": "1h",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_cluster_health",
        "description": (
            "Retorna um resumo da saúde do cluster k8s: "
            "status dos nós, pods com problema, uso de recursos gerais."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace específico para verificar. Omitir para todos.",
                },
            },
        },
    },
    {
        "name": "list_active_alerts",
        "description": "Lista os alertas ativos no Prometheus Alertmanager.",
        "input_schema": {
            "type": "object",
            "properties": {
                "severity": {
                    "type": "string",
                    "enum": ["critical", "warning", "info"],
                    "description": "Filtrar por severidade (opcional).",
                },
            },
        },
    },
    {
        "name": "get_pod_metrics",
        "description": "Retorna métricas detalhadas de CPU e memória de pods em um namespace.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace k8s (default: 'agent-platform')",
                },
            },
            "required": ["namespace"],
        },
    },
]


# ─── Implementações das tools ─────────────────────────────────────────────────

async def query_prometheus(query: str, time_range: str | None = None) -> dict[str, Any]:
    """Executa PromQL no Prometheus."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        if time_range:
            end = datetime.now(timezone.utc)
            url = f"{PROMETHEUS_URL}/api/v1/query_range"
            params = {
                "query": query,
                "start": f"now-{time_range}",
                "end": end.isoformat(),
                "step": _step_for_range(time_range),
            }
        else:
            url = f"{PROMETHEUS_URL}/api/v1/query"
            params = {"query": query}

        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            if data["status"] != "success":
                return {"error": f"Prometheus retornou status: {data['status']}"}

            results = data["data"]["result"]
            if not results:
                return {"message": "Nenhum resultado para a query.", "query": query}

            # Simplifica o output para o LLM
            simplified = []
            for r in results[:20]:  # limita a 20 séries
                metric = r.get("metric", {})
                if "value" in r:
                    simplified.append({"labels": metric, "value": r["value"][1]})
                elif "values" in r:
                    simplified.append({
                        "labels": metric,
                        "samples": len(r["values"]),
                        "last_value": r["values"][-1][1] if r["values"] else None,
                    })

            return {"query": query, "results": simplified, "total_series": len(results)}

        except httpx.ConnectError:
            return {"error": "Prometheus indisponível. Verifique se o pod está rodando."}
        except Exception as e:
            log.error("Erro ao consultar Prometheus", error=str(e))
            return {"error": str(e)}


async def query_loki(query: str, limit: int = 50, since: str = "1h") -> dict[str, Any]:
    """Consulta logs no Loki via LogQL."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        url = f"{LOKI_URL}/loki/api/v1/query_range"
        now_ns = int(datetime.now(timezone.utc).timestamp() * 1e9)
        since_seconds = _parse_duration_to_seconds(since)
        start_ns = now_ns - int(since_seconds * 1e9)

        params = {
            "query": query,
            "limit": limit,
            "start": start_ns,
            "end": now_ns,
            "direction": "backward",
        }

        try:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            streams = data.get("data", {}).get("result", [])
            if not streams:
                return {"message": "Nenhum log encontrado.", "query": query, "since": since}

            lines = []
            for stream in streams:
                labels = stream.get("stream", {})
                for ts, line in stream.get("values", []):
                    lines.append({
                        "timestamp": datetime.fromtimestamp(
                            int(ts) / 1e9, tz=timezone.utc
                        ).isoformat(),
                        "namespace": labels.get("namespace", ""),
                        "pod": labels.get("pod", ""),
                        "container": labels.get("container", ""),
                        "log": line[:500],  # trunca linhas muito longas
                    })

            lines.sort(key=lambda x: x["timestamp"], reverse=True)
            return {
                "query": query,
                "since": since,
                "total_lines": len(lines),
                "lines": lines[:limit],
            }

        except httpx.ConnectError:
            return {"error": "Loki indisponível. Verifique se o pod está rodando."}
        except Exception as e:
            log.error("Erro ao consultar Loki", error=str(e))
            return {"error": str(e)}


async def get_cluster_health(namespace: str | None = None) -> dict[str, Any]:
    """Saúde geral do cluster via múltiplas queries Prometheus."""
    queries = {
        "nodes_up": 'count(kube_node_status_condition{condition="Ready",status="true"})',
        "nodes_total": "count(kube_node_info)",
        "pods_running": f'count(kube_pod_status_phase{{phase="Running"{_ns_filter(namespace)}}})',
        "pods_pending": f'count(kube_pod_status_phase{{phase="Pending"{_ns_filter(namespace)}}})',
        "pods_failed": f'count(kube_pod_status_phase{{phase="Failed"{_ns_filter(namespace)}}})',
        "pods_crashloop": f'count(kube_pod_container_status_waiting_reason{{reason="CrashLoopBackOff"{_ns_filter(namespace)}}})',
        "cpu_usage_pct": "round(100 * avg(rate(container_cpu_usage_seconds_total{container!=\"\"}[5m])) / avg(kube_node_status_capacity{resource=\"cpu\"}))",
        "memory_usage_pct": "round(100 * sum(container_memory_working_set_bytes{container!=\"\"}) / sum(kube_node_status_capacity{resource=\"memory\"}))",
    }

    results = {}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for key, query in queries.items():
            try:
                resp = await client.get(
                    f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}
                )
                data = resp.json()
                series = data.get("data", {}).get("result", [])
                results[key] = series[0]["value"][1] if series else "N/A"
            except Exception:
                results[key] = "N/A"

    # Determina status geral
    failed = int(results.get("pods_failed") or 0)
    crashloop = int(results.get("pods_crashloop") or 0)
    overall = "healthy"
    if failed > 0 or crashloop > 0:
        overall = "degraded"

    return {
        "overall_status": overall,
        "namespace_filter": namespace or "all",
        "nodes": {
            "ready": results["nodes_up"],
            "total": results["nodes_total"],
        },
        "pods": {
            "running": results["pods_running"],
            "pending": results["pods_pending"],
            "failed": results["pods_failed"],
            "crashloop": results["pods_crashloop"],
        },
        "resources": {
            "cpu_usage_pct": results["cpu_usage_pct"],
            "memory_usage_pct": results["memory_usage_pct"],
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def list_active_alerts(severity: str | None = None) -> dict[str, Any]:
    """Lista alertas ativos no Prometheus."""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(f"{PROMETHEUS_URL}/api/v1/alerts")
            resp.raise_for_status()
            data = resp.json()

            alerts = data.get("data", {}).get("alerts", [])
            if severity:
                alerts = [a for a in alerts if a.get("labels", {}).get("severity") == severity]

            firing = [a for a in alerts if a.get("state") == "firing"]
            pending = [a for a in alerts if a.get("state") == "pending"]

            simplified = []
            for alert in firing + pending:
                simplified.append({
                    "name": alert["labels"].get("alertname", "unknown"),
                    "state": alert["state"],
                    "severity": alert["labels"].get("severity", "unknown"),
                    "summary": alert.get("annotations", {}).get("summary", ""),
                    "labels": {k: v for k, v in alert["labels"].items()
                               if k not in ("alertname", "severity")},
                })

            return {
                "total_firing": len(firing),
                "total_pending": len(pending),
                "alerts": simplified,
            }

        except httpx.ConnectError:
            return {"error": "Prometheus indisponível."}
        except Exception as e:
            return {"error": str(e)}


async def get_pod_metrics(namespace: str = "agent-platform") -> dict[str, Any]:
    """Métricas detalhadas de CPU e memória por pod."""
    queries = {
        "cpu": f'sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace="{namespace}",container!=""}}[5m]))',
        "memory_mb": f'sum by (pod) (container_memory_working_set_bytes{{namespace="{namespace}",container!=""}}) / 1024 / 1024',
    }

    pods_data: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for metric, query in queries.items():
            try:
                resp = await client.get(
                    f"{PROMETHEUS_URL}/api/v1/query", params={"query": query}
                )
                data = resp.json()
                for series in data.get("data", {}).get("result", []):
                    pod = series["metric"].get("pod", "unknown")
                    value = round(float(series["value"][1]), 4)
                    if pod not in pods_data:
                        pods_data[pod] = {}
                    pods_data[pod][metric] = value
            except Exception:
                pass

    return {
        "namespace": namespace,
        "pods": [
            {"pod": pod, **metrics}
            for pod, metrics in sorted(pods_data.items())
        ],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ─── Dispatcher ──────────────────────────────────────────────────────────────

async def execute_tool(tool_name: str, tool_input: dict) -> Any:
    """Dispatcher central — chama a função certa para cada tool."""
    dispatch = {
        "query_prometheus": lambda i: query_prometheus(i["query"], i.get("time_range")),
        "query_loki": lambda i: query_loki(i["query"], i.get("limit", 50), i.get("since", "1h")),
        "get_cluster_health": lambda i: get_cluster_health(i.get("namespace")),
        "list_active_alerts": lambda i: list_active_alerts(i.get("severity")),
        "get_pod_metrics": lambda i: get_pod_metrics(i.get("namespace", "agent-platform")),
    }
    fn = dispatch.get(tool_name)
    if not fn:
        return {"error": f"Tool desconhecida: {tool_name}"}
    return await fn(tool_input)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _step_for_range(time_range: str) -> str:
    steps = {"5m": "15s", "15m": "30s", "1h": "1m", "6h": "5m", "24h": "15m", "7d": "1h"}
    return steps.get(time_range, "1m")


def _parse_duration_to_seconds(duration: str) -> int:
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return int(duration[:-1]) * units.get(duration[-1], 60)


def _ns_filter(namespace: str | None) -> str:
    return f',namespace="{namespace}"' if namespace else ""
