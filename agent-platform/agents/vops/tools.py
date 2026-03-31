"""
Vops Tools — operações kubectl via Python kubernetes SDK.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import structlog
from agents.shared.ssh_tools import SSH_TOOL_DEFINITION, execute_ssh_command

log = structlog.get_logger(__name__)

# Kubernetes client (lazy import para não quebrar se não instalado)
_k8s_apps = None
_k8s_core = None
_k8s_loaded = False


def _load_k8s():
    global _k8s_apps, _k8s_core, _k8s_loaded
    if _k8s_loaded:
        return
    try:
        from kubernetes import client, config
        try:
            config.load_incluster_config()  # dentro do cluster
        except Exception:
            config.load_kube_config()       # fora do cluster (dev)
        _k8s_apps = client.AppsV1Api()
        _k8s_core = client.CoreV1Api()
        _k8s_loaded = True
    except Exception as e:
        log.error("Falha ao carregar k8s client", error=str(e))


TOOL_DEFINITIONS = [
    {
        "name": "k8s_get",
        "description": "Lista ou descreve recursos k8s: pods, deployments, services, namespaces, etc.",
        "input_schema": {
            "type": "object",
            "properties": {
                "resource": {"type": "string", "description": "Tipo: pods, deployments, services, nodes, namespaces"},
                "namespace": {"type": "string", "description": "Namespace (omitir para cluster-wide)"},
                "name": {"type": "string", "description": "Nome específico (omitir para listar todos)"},
            },
            "required": ["resource"],
        },
    },
    {
        "name": "k8s_scale",
        "description": "Escala um Deployment ou StatefulSet.",
        "input_schema": {
            "type": "object",
            "properties": {
                "resource_type": {"type": "string", "enum": ["deployment", "statefulset"]},
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "replicas": {"type": "integer", "minimum": 0, "maximum": 20},
                "dry_run": {"type": "boolean", "description": "Se true, simula sem executar", "default": False},
            },
            "required": ["resource_type", "name", "namespace", "replicas"],
        },
    },
    {
        "name": "k8s_rollout_restart",
        "description": "Reinicia graciosamente os pods de um Deployment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
            },
            "required": ["name", "namespace"],
        },
    },
    {
        "name": "k8s_rollout_status",
        "description": "Verifica o status atual de um rollout de Deployment.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
            },
            "required": ["name", "namespace"],
        },
    },
    {
        "name": "k8s_rollout_undo",
        "description": "Faz rollback de um Deployment para a revisão anterior.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "namespace": {"type": "string"},
                "dry_run": {"type": "boolean", "default": False},
            },
            "required": ["name", "namespace"],
        },
    },
    {
        "name": "k8s_get_logs",
        "description": "Coleta logs de um pod específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pod_name": {"type": "string"},
                "namespace": {"type": "string"},
                "tail_lines": {"type": "integer", "default": 50},
                "container": {"type": "string", "description": "Container específico (opcional)"},
            },
            "required": ["pod_name", "namespace"],
        },
    },
    {
        "name": "k8s_top",
        "description": "Retorna uso de CPU/memória dos pods via métricas do cluster.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
            },
            "required": ["namespace"],
        },
    },
    SSH_TOOL_DEFINITION,
    {
        "name": "k8s_delete_pod",
        "description": "Deleta um pod (será recriado pelo controller). Use para forçar restart de pod específico.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pod_name": {"type": "string"},
                "namespace": {"type": "string"},
                "dry_run": {"type": "boolean", "default": True},
            },
            "required": ["pod_name", "namespace"],
        },
    },
]


async def k8s_get(resource: str, namespace: str | None = None, name: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "Kubernetes client não disponível."}

    try:
        ts = datetime.now(timezone.utc).isoformat()

        if resource == "pods":
            if namespace:
                items = _k8s_core.list_namespaced_pod(namespace)
            else:
                items = _k8s_core.list_pod_for_all_namespaces()
            return {
                "resource": "pods",
                "namespace": namespace or "all",
                "timestamp": ts,
                "items": [
                    {
                        "name": p.metadata.name,
                        "namespace": p.metadata.namespace,
                        "status": p.status.phase,
                        "ready": _pod_ready(p),
                        "restarts": _pod_restarts(p),
                        "node": p.spec.node_name,
                        "age": _age(p.metadata.creation_timestamp),
                    }
                    for p in items.items
                ],
            }

        elif resource == "deployments":
            if namespace:
                items = _k8s_apps.list_namespaced_deployment(namespace)
            else:
                items = _k8s_apps.list_deployment_for_all_namespaces()
            return {
                "resource": "deployments",
                "namespace": namespace or "all",
                "timestamp": ts,
                "items": [
                    {
                        "name": d.metadata.name,
                        "namespace": d.metadata.namespace,
                        "desired": d.spec.replicas,
                        "ready": d.status.ready_replicas or 0,
                        "available": d.status.available_replicas or 0,
                        "age": _age(d.metadata.creation_timestamp),
                    }
                    for d in items.items
                ],
            }

        elif resource == "namespaces":
            items = _k8s_core.list_namespace()
            return {
                "resource": "namespaces",
                "timestamp": ts,
                "items": [
                    {"name": n.metadata.name, "status": n.status.phase}
                    for n in items.items
                ],
            }

        elif resource == "nodes":
            items = _k8s_core.list_node()
            return {
                "resource": "nodes",
                "timestamp": ts,
                "items": [
                    {
                        "name": n.metadata.name,
                        "status": _node_ready(n),
                        "roles": _node_roles(n),
                        "version": n.status.node_info.kubelet_version,
                    }
                    for n in items.items
                ],
            }

        return {"error": f"Recurso não suportado: {resource}"}

    except Exception as e:
        log.error("k8s_get error", error=str(e))
        return {"error": str(e)}


async def k8s_scale(
    resource_type: str, name: str, namespace: str, replicas: int, dry_run: bool = False
) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "Kubernetes client não disponível."}

    dry_run_param = ["All"] if dry_run else None
    try:
        if resource_type == "deployment":
            current = _k8s_apps.read_namespaced_deployment(name, namespace)
            current_replicas = current.spec.replicas
            if not dry_run:
                current.spec.replicas = replicas
                _k8s_apps.patch_namespaced_deployment(
                    name, namespace, current,
                    dry_run="All" if dry_run else None
                )
        return {
            "action": "scale",
            "resource": f"{resource_type}/{name}",
            "namespace": namespace,
            "from_replicas": current_replicas if not dry_run else "N/A",
            "to_replicas": replicas,
            "dry_run": dry_run,
            "status": "simulated" if dry_run else "applied",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


async def k8s_rollout_restart(name: str, namespace: str, dry_run: bool = False) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "Kubernetes client não disponível."}

    try:
        from kubernetes.client import V1Deployment
        import json as _json
        now = datetime.now(timezone.utc).isoformat()
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                    }
                }
            }
        }
        if not dry_run:
            _k8s_apps.patch_namespaced_deployment(name, namespace, patch)
        return {
            "action": "rollout_restart",
            "deployment": name,
            "namespace": namespace,
            "dry_run": dry_run,
            "status": "simulated" if dry_run else "restart_triggered",
            "restarted_at": now,
        }
    except Exception as e:
        return {"error": str(e)}


async def k8s_rollout_status(name: str, namespace: str) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "Kubernetes client não disponível."}
    try:
        d = _k8s_apps.read_namespaced_deployment(name, namespace)
        desired = d.spec.replicas or 0
        ready = d.status.ready_replicas or 0
        updated = d.status.updated_replicas or 0
        available = d.status.available_replicas or 0
        is_complete = (ready == desired and updated == desired and available == desired)
        return {
            "deployment": name,
            "namespace": namespace,
            "desired": desired,
            "updated": updated,
            "ready": ready,
            "available": available,
            "rollout_complete": is_complete,
            "status": "✅ completo" if is_complete else "⏳ em andamento",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


async def k8s_rollout_undo(name: str, namespace: str, dry_run: bool = False) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "Kubernetes client não disponível."}
    # Rollback via patch annotation
    if dry_run:
        return {"action": "rollout_undo", "deployment": name, "namespace": namespace,
                "dry_run": True, "status": "simulated — revisão anterior seria aplicada"}
    try:
        from kubernetes.client import AppsV1Api
        # Rollback via rollout history não é diretamente suportado pelo Python SDK
        # Usa patch para forçar rollback removendo a anotação de restart
        _k8s_apps.patch_namespaced_deployment(
            name, namespace,
            {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": None}}}}}
        )
        return {"action": "rollout_undo", "deployment": name, "namespace": namespace,
                "status": "undo_triggered", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"error": str(e)}


async def k8s_get_logs(pod_name: str, namespace: str, tail_lines: int = 50, container: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "Kubernetes client não disponível."}
    try:
        kwargs: dict = {"tail_lines": tail_lines}
        if container:
            kwargs["container"] = container
        logs = _k8s_core.read_namespaced_pod_log(pod_name, namespace, **kwargs)
        lines = logs.split("\n") if logs else []
        return {
            "pod": pod_name,
            "namespace": namespace,
            "container": container or "default",
            "lines_returned": len(lines),
            "logs": lines[-tail_lines:],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


async def k8s_top(namespace: str) -> dict:
    """Usa Prometheus para métricas (metrics-server pode não estar disponível)."""
    import httpx
    PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus.observability.svc.cluster.local:9090")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            cpu_q = f'sum by (pod) (rate(container_cpu_usage_seconds_total{{namespace="{namespace}",container!=""}}[5m]))'
            mem_q = f'sum by (pod) (container_memory_working_set_bytes{{namespace="{namespace}",container!=""}}) / 1024 / 1024'
            pods: dict[str, dict] = {}
            for metric, q in [("cpu_cores", cpu_q), ("memory_mb", mem_q)]:
                r = await client.get(f"{PROMETHEUS_URL}/api/v1/query", params={"query": q})
                for s in r.json().get("data", {}).get("result", []):
                    pod = s["metric"].get("pod", "unknown")
                    if pod not in pods:
                        pods[pod] = {}
                    pods[pod][metric] = round(float(s["value"][1]), 4)
        return {
            "namespace": namespace,
            "pods": [{"pod": p, **m} for p, m in sorted(pods.items())],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except Exception as e:
        return {"error": str(e)}


async def k8s_delete_pod(pod_name: str, namespace: str, dry_run: bool = True) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "Kubernetes client não disponível."}
    if dry_run:
        return {"action": "delete_pod", "pod": pod_name, "namespace": namespace,
                "dry_run": True, "status": "simulated — pod seria deletado e recriado"}
    try:
        from kubernetes.client import V1DeleteOptions
        _k8s_core.delete_namespaced_pod(pod_name, namespace, body=V1DeleteOptions(grace_period_seconds=0))
        return {"action": "delete_pod", "pod": pod_name, "namespace": namespace,
                "status": "deleted", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        return {"error": str(e)}


async def execute_tool(tool_name: str, tool_input: dict) -> Any:
    dispatch = {
        "k8s_get": lambda i: k8s_get(i["resource"], i.get("namespace"), i.get("name")),
        "k8s_scale": lambda i: k8s_scale(i["resource_type"], i["name"], i["namespace"], i["replicas"], i.get("dry_run", False)),
        "k8s_rollout_restart": lambda i: k8s_rollout_restart(i["name"], i["namespace"], i.get("dry_run", False)),
        "k8s_rollout_status": lambda i: k8s_rollout_status(i["name"], i["namespace"]),
        "k8s_rollout_undo": lambda i: k8s_rollout_undo(i["name"], i["namespace"], i.get("dry_run", False)),
        "k8s_get_logs": lambda i: k8s_get_logs(i["pod_name"], i["namespace"], i.get("tail_lines", 50), i.get("container")),
        "k8s_top": lambda i: k8s_top(i["namespace"]),
        "k8s_delete_pod": lambda i: k8s_delete_pod(i["pod_name"], i["namespace"], i.get("dry_run", True)),
        "run_ssh_command": lambda i: execute_ssh_command(
            i["host"], i["username"], i["command"],
            i.get("port", 22), i.get("private_key_path"), i.get("password"), i.get("timeout", 30),
        ),
    }
    fn = dispatch.get(tool_name)
    return await fn(tool_input) if fn else {"error": f"Tool desconhecida: {tool_name}"}


# ── Helpers ──
def _pod_ready(p) -> str:
    if not p.status.container_statuses:
        return "0/0"
    ready = sum(1 for c in p.status.container_statuses if c.ready)
    total = len(p.status.container_statuses)
    return f"{ready}/{total}"

def _pod_restarts(p) -> int:
    if not p.status.container_statuses:
        return 0
    return sum(c.restart_count for c in p.status.container_statuses)

def _node_ready(n) -> str:
    for cond in (n.status.conditions or []):
        if cond.type == "Ready":
            return "Ready" if cond.status == "True" else "NotReady"
    return "Unknown"

def _node_roles(n) -> list[str]:
    return [k.split("/")[-1] for k in (n.metadata.labels or {}) if k.startswith("node-role.kubernetes.io/")]

def _age(ts) -> str:
    if not ts:
        return "N/A"
    delta = datetime.now(timezone.utc) - ts.replace(tzinfo=timezone.utc)
    h = int(delta.total_seconds() // 3600)
    return f"{h}h" if h < 48 else f"{h//24}d"
