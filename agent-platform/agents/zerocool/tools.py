"""
Ferramentas do agente Zerocool — White Hat Pentester.
Confirma vulnerabilidades encontradas pelo CyberT com evidências controladas.
Toda ação requer request_id aprovado pelo Adelmo.
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ─────────────────────────────────────────────────────────────────
# helpers internos
# ─────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_k8s():
    """Carrega cliente Kubernetes (incluster ou kubeconfig)."""
    try:
        from kubernetes import client, config
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        return client
    except ImportError:
        return None


# ─────────────────────────────────────────────────────────────────
# tool: confirm_rbac_escalation
# ─────────────────────────────────────────────────────────────────

async def confirm_rbac_escalation(
    request_id: str,
    target_role: str,
    target_namespace: str = "default",
) -> dict[str, Any]:
    """
    Confirma se um ClusterRole com wildcards permite escalonamento real de privilégios.
    Simula o que um atacante com acesso ao ServiceAccount poderia fazer.
    """
    ts = _now()
    k8s = _load_k8s()

    evidence: list[str] = []
    accessible_resources: list[str] = []

    if k8s:
        try:
            rbac = k8s.RbacAuthorizationV1Api()

            # Busca a ClusterRole alvo
            try:
                role = rbac.read_cluster_role(name=target_role)
                rules = role.rules or []
            except Exception:
                # Tenta como Role no namespace
                try:
                    role = rbac.read_namespaced_role(
                        name=target_role,
                        namespace=target_namespace,
                    )
                    rules = role.rules or []
                except Exception as e:
                    return {
                        "request_id": request_id,
                        "confirmed": False,
                        "error": f"Role '{target_role}' não encontrada: {str(e)}",
                        "timestamp": ts,
                    }

            # Analisa regras para wildcards perigosos
            for rule in rules:
                verbs = rule.verbs or []
                resources = rule.resources or []
                api_groups = rule.api_groups or []

                if "*" in verbs and "*" in resources:
                    accessible_resources.append("ALL (*)")
                    evidence.append(
                        f"[{ts}] CRÍTICO: Wildcards completos encontrados — "
                        f"verbs=* resources=* apiGroups={api_groups}"
                    )
                elif "*" in verbs:
                    for res in resources:
                        accessible_resources.append(f"{res}:ALL_VERBS")
                        evidence.append(
                            f"[{ts}] ALTO: Todos os verbs em '{res}' — "
                            f"pode criar/deletar/patch qualquer {res}"
                        )
                elif any(v in verbs for v in ["create", "patch", "update", "delete"]):
                    for res in resources:
                        if res in ["secrets", "pods", "deployments", "clusterroles", "clusterrolebindings"]:
                            accessible_resources.append(f"{res}:{','.join(verbs)}")
                            evidence.append(
                                f"[{ts}] ALTO: Acesso a recurso sensível '{res}' "
                                f"com verbs={verbs}"
                            )

            confirmed = len(accessible_resources) > 0

            return {
                "request_id": request_id,
                "target_role": target_role,
                "confirmed": confirmed,
                "accessible_resources": accessible_resources,
                "evidence_log": evidence,
                "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H" if confirmed else None,
                "cvss_score": 9.9 if confirmed else None,
                "cve_reference": "CWE-269: Improper Privilege Management",
                "owasp": "A01:2021 – Broken Access Control",
                "timestamp": ts,
                "recommendation": (
                    "Remover wildcards do ClusterRole. "
                    "Aplicar princípio do menor privilégio. "
                    "Usar Roles com escopo de namespace ao invés de ClusterRoles."
                ),
            }

        except Exception as e:
            log.error("Zerocool: erro ao confirmar RBAC", error=str(e))
            return {"request_id": request_id, "error": str(e), "timestamp": ts}

    # Modo simulado (sem k8s disponível)
    return {
        "request_id": request_id,
        "target_role": target_role,
        "confirmed": True,
        "accessible_resources": ["secrets:get,list", "pods:create,delete", "clusterroles:*"],
        "evidence_log": [
            f"[{ts}] SIMULADO: ClusterRole '{target_role}' possui wildcard em resources sensíveis",
            f"[{ts}] SIMULADO: Acesso a secrets confirmado via SA impersonation",
        ],
        "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H",
        "cvss_score": 9.9,
        "cve_reference": "CWE-269: Improper Privilege Management",
        "owasp": "A01:2021 – Broken Access Control",
        "timestamp": ts,
        "mode": "simulated",
    }


# ─────────────────────────────────────────────────────────────────
# tool: test_secret_exposure
# ─────────────────────────────────────────────────────────────────

async def test_secret_exposure(
    request_id: str,
    namespace: str,
    secret_name: str,
) -> dict[str, Any]:
    """
    Testa se um Secret está acessível via API k8s sem autenticação adequada.
    Confirma exposição de credenciais em env vars ou volumes.
    Retorna evidência sem expor o valor real do secret.
    """
    ts = _now()
    k8s = _load_k8s()

    if k8s:
        try:
            v1 = k8s.CoreV1Api()
            secret = v1.read_namespaced_secret(name=secret_name, namespace=namespace)

            # Lista as chaves (não os valores) para evidência
            keys = list(secret.data.keys()) if secret.data else []
            sensitive_keys = [
                k for k in keys
                if any(s in k.lower() for s in [
                    "password", "token", "key", "secret", "credential",
                    "api_key", "apikey", "private", "cert", "passwd",
                ])
            ]

            evidence_log = [
                f"[{ts}] Secret '{secret_name}' lido via API Kubernetes sem restrição de acesso",
                f"[{ts}] Total de chaves no secret: {len(keys)}",
                f"[{ts}] Chaves sensíveis identificadas: {sensitive_keys}",
                f"[{ts}] PROVA: Secret acessível por qualquer SA com permissão 'get' em secrets/{namespace}",
            ]

            return {
                "request_id": request_id,
                "namespace": namespace,
                "secret_name": secret_name,
                "confirmed": True,
                "sensitive_keys_found": sensitive_keys,
                "total_keys": len(keys),
                "evidence_log": evidence_log,
                "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N",
                "cvss_score": 6.5,
                "cve_reference": "CWE-200: Exposure of Sensitive Information",
                "owasp": "A02:2021 – Cryptographic Failures",
                "timestamp": ts,
                "recommendation": (
                    "Aplicar RBAC restritivo: usar 'resourceNames' para limitar acesso a secrets específicos. "
                    "Considerar uso de Vault ou External Secrets Operator. "
                    "Rotacionar credenciais expostas imediatamente."
                ),
            }

        except k8s.ApiException as e:  # type: ignore
            if e.status == 403:
                return {
                    "request_id": request_id,
                    "namespace": namespace,
                    "secret_name": secret_name,
                    "confirmed": False,
                    "message": "Acesso negado — RBAC está corretamente restritivo",
                    "timestamp": ts,
                }
            return {
                "request_id": request_id,
                "error": str(e),
                "timestamp": ts,
            }
        except Exception as e:
            return {"request_id": request_id, "error": str(e), "timestamp": ts}

    # Modo simulado
    return {
        "request_id": request_id,
        "namespace": namespace,
        "secret_name": secret_name,
        "confirmed": True,
        "sensitive_keys_found": ["ANTHROPIC_API_KEY", "DB_PASSWORD", "JWT_SECRET"],
        "total_keys": 5,
        "evidence_log": [
            f"[{ts}] SIMULADO: Secret '{secret_name}' acessível via kubectl get secret",
            f"[{ts}] SIMULADO: Credenciais sensíveis expostas sem criptografia adicional",
        ],
        "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N",
        "cvss_score": 6.5,
        "timestamp": ts,
        "mode": "simulated",
    }


# ─────────────────────────────────────────────────────────────────
# tool: scan_network_reachability
# ─────────────────────────────────────────────────────────────────

async def scan_network_reachability(
    request_id: str,
    source_namespace: str,
    target_namespace: str,
    target_pod_selector: str = "",
) -> dict[str, Any]:
    """
    Verifica conectividade entre pods em namespaces diferentes para confirmar
    ausência de NetworkPolicy efetiva (lateral movement possível).
    """
    ts = _now()
    k8s = _load_k8s()

    reachable_pods: list[dict] = []

    if k8s:
        try:
            v1 = k8s.CoreV1Api()
            net = k8s.NetworkingV1Api()

            # Lista pods no target namespace
            pods = v1.list_namespaced_pod(namespace=target_namespace)

            # Verifica NetworkPolicies no target namespace
            policies = net.list_namespaced_network_policy(namespace=target_namespace)
            has_policies = len(policies.items) > 0

            for pod in pods.items:
                pod_name = pod.metadata.name
                pod_ip = pod.status.pod_ip
                labels = pod.metadata.labels or {}

                if pod.status.phase == "Running" and pod_ip:
                    reachable = not has_policies  # sem policy = acessível

                    if reachable:
                        # Identifica portas expostas
                        ports = []
                        for container in (pod.spec.containers or []):
                            for port in (container.ports or []):
                                ports.append({
                                    "container": container.name,
                                    "port": port.container_port,
                                    "protocol": port.protocol or "TCP",
                                })

                        reachable_pods.append({
                            "pod": pod_name,
                            "ip": pod_ip,
                            "labels": labels,
                            "exposed_ports": ports,
                        })

            evidence_log = [
                f"[{ts}] Varredura de alcançabilidade: {source_namespace} → {target_namespace}",
                f"[{ts}] NetworkPolicies no target: {'Nenhuma — VULNERÁVEL' if not has_policies else 'Configuradas'}",
                f"[{ts}] Pods alcançáveis: {len(reachable_pods)}",
            ]
            if reachable_pods:
                evidence_log.append(
                    f"[{ts}] PROVA: Lateral movement possível para {len(reachable_pods)} pods"
                )

            return {
                "request_id": request_id,
                "source_namespace": source_namespace,
                "target_namespace": target_namespace,
                "confirmed": len(reachable_pods) > 0,
                "reachable_pods": reachable_pods,
                "has_network_policies": has_policies,
                "evidence_log": evidence_log,
                "cvss_vector": "CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:C/C:H/I:H/A:H" if reachable_pods else None,
                "cvss_score": 9.0 if reachable_pods else None,
                "cve_reference": "CWE-923: Improper Restriction of Communication Channel",
                "owasp": "A05:2021 – Security Misconfiguration",
                "timestamp": ts,
                "recommendation": (
                    "Criar NetworkPolicies default-deny em todos os namespaces. "
                    "Permitir apenas tráfego explicitamente necessário. "
                    "Usar namespaces com labels para seletor de políticas."
                ),
            }

        except Exception as e:
            return {"request_id": request_id, "error": str(e), "timestamp": ts}

    # Modo simulado
    return {
        "request_id": request_id,
        "source_namespace": source_namespace,
        "target_namespace": target_namespace,
        "confirmed": True,
        "reachable_pods": [
            {
                "pod": "orchestrator-7d8f9b-xk2p1",
                "ip": "10.244.1.15",
                "labels": {"app": "orchestrator"},
                "exposed_ports": [{"container": "orchestrator", "port": 8000, "protocol": "TCP"}],
            },
            {
                "pod": "redis-0",
                "ip": "10.244.1.20",
                "labels": {"app": "redis"},
                "exposed_ports": [{"container": "redis", "port": 6379, "protocol": "TCP"}],
            },
        ],
        "has_network_policies": False,
        "evidence_log": [
            f"[{ts}] SIMULADO: Sem NetworkPolicy em '{target_namespace}'",
            f"[{ts}] SIMULADO: Lateral movement confirmado para pods críticos",
        ],
        "cvss_score": 9.0,
        "timestamp": ts,
        "mode": "simulated",
    }


# ─────────────────────────────────────────────────────────────────
# tool: check_api_server_exposure
# ─────────────────────────────────────────────────────────────────

async def check_api_server_exposure(request_id: str) -> dict[str, Any]:
    """
    Verifica se o kube-apiserver está exposto externamente via NodePort
    ou se permite acesso anônimo.
    """
    ts = _now()
    k8s = _load_k8s()

    findings: list[dict] = []

    if k8s:
        try:
            v1 = k8s.CoreV1Api()

            # Verifica serviço kubernetes no default namespace
            svc = v1.read_namespaced_service(name="kubernetes", namespace="default")
            port = svc.spec.ports[0].port if svc.spec.ports else 443
            svc_type = svc.spec.type

            evidence_log = [
                f"[{ts}] kube-apiserver service type: {svc_type}",
                f"[{ts}] Port: {port}",
            ]

            # Testa anonymous access (sem autenticação)
            import httpx
            api_host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
            try:
                async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
                    resp = await client.get(f"https://{api_host}:{port}/api/v1/namespaces")
                    if resp.status_code == 200:
                        findings.append({
                            "type": "ANONYMOUS_ACCESS",
                            "severity": "CRÍTICO",
                            "detail": "kube-apiserver aceita requisições sem autenticação",
                        })
                        evidence_log.append(
                            f"[{ts}] CRÍTICO: /api/v1/namespaces retornou 200 sem token"
                        )
                    elif resp.status_code == 401:
                        evidence_log.append(
                            f"[{ts}] OK: Autenticação requerida (401)"
                        )
            except Exception:
                evidence_log.append(f"[{ts}] API server não alcançável externamente (esperado)")

            confirmed = len(findings) > 0 or svc_type == "NodePort"

            return {
                "request_id": request_id,
                "confirmed": confirmed,
                "service_type": svc_type,
                "api_port": port,
                "findings": findings,
                "evidence_log": evidence_log,
                "cvss_score": 10.0 if any(f["type"] == "ANONYMOUS_ACCESS" for f in findings) else (
                    7.5 if confirmed else None
                ),
                "timestamp": ts,
                "recommendation": (
                    "Garantir que kube-apiserver não seja exposto como NodePort. "
                    "Desabilitar anonymous auth (--anonymous-auth=false). "
                    "Usar RBAC + audit logging em todas as requisições."
                ),
            }

        except Exception as e:
            return {"request_id": request_id, "error": str(e), "timestamp": ts}

    return {
        "request_id": request_id,
        "confirmed": False,
        "service_type": "ClusterIP",
        "api_port": 443,
        "findings": [],
        "evidence_log": [f"[{ts}] kube-apiserver: ClusterIP, autenticação OK"],
        "cvss_score": None,
        "timestamp": ts,
        "mode": "simulated",
    }


# ─────────────────────────────────────────────────────────────────
# tool: generate_pentest_report
# ─────────────────────────────────────────────────────────────────

async def generate_pentest_report(
    request_id: str,
    target: str,
    vulnerability: str,
    severity: str,
    evidence_log: list[str],
    cvss_score: float | None = None,
    cvss_vector: str | None = None,
    cve_reference: str | None = None,
    recommendation: str = "",
) -> dict[str, Any]:
    """
    Gera relatório técnico de pentest com evidências, CVSS e recomendações.
    Salva o relatório como artefato na pasta de outputs.
    """
    ts = _now()

    report_content = f"""# Relatório de Pentest — Zerocool
**Request ID**: `{request_id}`
**Timestamp**: {ts}
**Target**: {target}
**Autorizado por**: Adelmo

---

## Vulnerabilidade
**{vulnerability}**
**Severidade**: {severity}

### Score CVSS
- **Score**: {cvss_score or 'N/A'}
- **Vector**: `{cvss_vector or 'N/A'}`
- **Referência**: {cve_reference or 'N/A'}

---

## Evidências Coletadas

```
{chr(10).join(evidence_log)}
```

---

## Remediação
{recommendation}

---

*Relatório gerado automaticamente por Zerocool. Para arquivamento, enviar ao Metatron.*
"""

    # Salva o relatório como artefato
    output_dir = "/app/reports"
    os.makedirs(output_dir, exist_ok=True)
    report_filename = f"pentest_{request_id[:8]}_{ts.replace(':', '-').replace('T', '_')}.md"
    report_path = os.path.join(output_dir, report_filename)

    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)
        saved = True
    except Exception as e:
        log.warning("Zerocool: não foi possível salvar relatório em disco", error=str(e))
        saved = False

    return {
        "request_id": request_id,
        "report_generated": True,
        "report_filename": report_filename,
        "report_saved": saved,
        "report_path": report_path if saved else None,
        "report_content": report_content,
        "summary": {
            "target": target,
            "vulnerability": vulnerability,
            "severity": severity,
            "cvss_score": cvss_score,
            "evidence_count": len(evidence_log),
        },
        "timestamp": ts,
    }


# ─────────────────────────────────────────────────────────────────
# tool: generate_proof_of_concept
# ─────────────────────────────────────────────────────────────────

async def generate_proof_of_concept(
    request_id: str,
    vulnerability_type: str,
    target: str,
    evidence: str,
) -> dict[str, Any]:
    """
    Cria um PoC mínimo e seguro para demonstrar a vulnerabilidade.
    O PoC é apenas demonstrativo — não executa payloads destrutivos.
    """
    ts = _now()

    poc_templates = {
        "rbac_escalation": f"""#!/bin/bash
# PoC: RBAC Privilege Escalation
# Request ID: {request_id}
# Target: {target}
# ATENÇÃO: Apenas demonstrativo — autorizado por Adelmo

# 1. Identifica ServiceAccount com ClusterRole wildcard
kubectl get clusterrolebindings -o json | \\
  jq '.items[] | select(.roleRef.name == "{target}") | .subjects[]'

# 2. Demonstra acesso a secrets via SA impersonation
# kubectl --as=system:serviceaccount:default:AFFECTED_SA get secrets -A

# Resultado esperado: acesso a todos os secrets do cluster
# Evidência: {evidence}
""",
        "secret_exposure": f"""#!/bin/bash
# PoC: Secret Exposure via k8s API
# Request ID: {request_id}
# Target: {target}

# 1. Acessa o secret diretamente via API (sem criptografia adicional)
kubectl get secret {target} -o jsonpath='{{.data}}' | base64 -d

# Resultado: credenciais expostas em texto claro
# Evidência: {evidence}
""",
        "network_lateral_movement": f"""#!/bin/bash
# PoC: Network Lateral Movement (sem NetworkPolicy)
# Request ID: {request_id}
# Target: {target}

# 1. A partir de qualquer pod no cluster, acessa pods sem restrição
# kubectl exec -n attacker-ns attacker-pod -- \\
#   curl -s http://{target}:8080/health

# 2. Redis acessível sem autenticação entre namespaces
# kubectl exec -n attacker-ns attacker-pod -- \\
#   redis-cli -h redis.agent-platform.svc.cluster.local ping

# Resultado: movimento lateral irrestrito entre pods
# Evidência: {evidence}
""",
    }

    poc_type = "rbac_escalation"
    if "secret" in vulnerability_type.lower():
        poc_type = "secret_exposure"
    elif "network" in vulnerability_type.lower() or "lateral" in vulnerability_type.lower():
        poc_type = "network_lateral_movement"

    poc_content = poc_templates.get(poc_type, f"""#!/bin/bash
# PoC: {vulnerability_type}
# Request ID: {request_id}
# Target: {target}
# Evidência: {evidence}
""")

    return {
        "request_id": request_id,
        "poc_type": poc_type,
        "poc_content": poc_content,
        "vulnerability_type": vulnerability_type,
        "target": target,
        "disclaimer": "PoC gerado para fins de documentação. Não executar sem autorização renovada.",
        "timestamp": ts,
    }


# ─────────────────────────────────────────────────────────────────
# tool: archive_to_metatron
# ─────────────────────────────────────────────────────────────────

async def archive_to_metatron(
    request_id: str,
    report_content: str,
    vulnerability: str,
    severity: str,
    cvss_score: float | None = None,
) -> dict[str, Any]:
    """
    Envia relatório de pentest ao Metatron para arquivamento permanente.
    Retorna confirmação de arquivamento com referência.
    """
    ts = _now()
    archive_ref = f"PENTEST-{request_id[:8].upper()}-{ts[:10].replace('-', '')}"

    # Prepara payload para Metatron (via NATS em produção)
    # Por ora, salva localmente como artefato arquivado
    archive_dir = "/app/archives"
    os.makedirs(archive_dir, exist_ok=True)
    archive_path = os.path.join(archive_dir, f"{archive_ref}.md")

    archived_content = f"""---
archive_ref: {archive_ref}
request_id: {request_id}
archived_at: {ts}
archived_by: Zerocool
vulnerability: {vulnerability}
severity: {severity}
cvss_score: {cvss_score}
---

{report_content}
"""

    try:
        with open(archive_path, "w", encoding="utf-8") as f:
            f.write(archived_content)
        archived = True
    except Exception as e:
        log.warning("Zerocool: erro ao arquivar para Metatron", error=str(e))
        archived = False

    return {
        "request_id": request_id,
        "archive_ref": archive_ref,
        "archived": archived,
        "archive_path": archive_path if archived else None,
        "message": (
            f"✅ Relatório arquivado com referência `{archive_ref}`"
            if archived
            else "⚠️ Falha ao arquivar — Metatron não disponível"
        ),
        "timestamp": ts,
    }


# ─────────────────────────────────────────────────────────────────
# TOOL_DEFINITIONS — Schema para Claude API
# ─────────────────────────────────────────────────────────────────

TOOL_DEFINITIONS = [
    {
        "name": "confirm_rbac_escalation",
        "description": (
            "Confirma se um ClusterRole/Role com wildcards permite escalonamento real de privilégios. "
            "Verifica as regras da role e identifica acesso a recursos sensíveis. "
            "Requer request_id aprovado pelo Adelmo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "ID de autorização aprovado pelo Adelmo",
                },
                "target_role": {
                    "type": "string",
                    "description": "Nome da ClusterRole ou Role a confirmar",
                },
                "target_namespace": {
                    "type": "string",
                    "description": "Namespace (para Roles com escopo de namespace)",
                    "default": "default",
                },
            },
            "required": ["request_id", "target_role"],
        },
    },
    {
        "name": "test_secret_exposure",
        "description": (
            "Testa se um Secret Kubernetes está acessível via API sem restrições adequadas. "
            "Confirma exposição de credenciais sensíveis. "
            "Retorna evidência sem expor o valor real do secret. "
            "Requer request_id aprovado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "ID de autorização"},
                "namespace": {"type": "string", "description": "Namespace do secret"},
                "secret_name": {"type": "string", "description": "Nome do Secret a testar"},
            },
            "required": ["request_id", "namespace", "secret_name"],
        },
    },
    {
        "name": "scan_network_reachability",
        "description": (
            "Verifica conectividade entre pods em namespaces diferentes para confirmar "
            "ausência de NetworkPolicy efetiva. Detecta possibilidade de lateral movement. "
            "Requer request_id aprovado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "ID de autorização"},
                "source_namespace": {
                    "type": "string",
                    "description": "Namespace de origem do potencial atacante",
                },
                "target_namespace": {
                    "type": "string",
                    "description": "Namespace alvo a verificar alcançabilidade",
                },
                "target_pod_selector": {
                    "type": "string",
                    "description": "Label selector opcional (ex: app=redis)",
                    "default": "",
                },
            },
            "required": ["request_id", "source_namespace", "target_namespace"],
        },
    },
    {
        "name": "check_api_server_exposure",
        "description": (
            "Verifica se o kube-apiserver está exposto externamente via NodePort "
            "ou se permite acesso anônimo. "
            "Requer request_id aprovado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string", "description": "ID de autorização"},
            },
            "required": ["request_id"],
        },
    },
    {
        "name": "generate_pentest_report",
        "description": (
            "Gera relatório técnico de pentest com todas as evidências coletadas, "
            "score CVSS, vetor de ataque, referências CVE/CWE e recomendações de remediação. "
            "Salva como artefato permanente."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "target": {"type": "string", "description": "Alvo do pentest"},
                "vulnerability": {
                    "type": "string",
                    "description": "Descrição da vulnerabilidade confirmada",
                },
                "severity": {
                    "type": "string",
                    "enum": ["CRÍTICO", "ALTO", "MÉDIO", "BAIXO"],
                },
                "evidence_log": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de evidências coletadas durante o teste",
                },
                "cvss_score": {"type": "number", "description": "Score CVSS 3.1 (0-10)"},
                "cvss_vector": {"type": "string", "description": "Vetor CVSS completo"},
                "cve_reference": {"type": "string", "description": "CVE ou CWE de referência"},
                "recommendation": {
                    "type": "string",
                    "description": "Recomendação de remediação detalhada",
                },
            },
            "required": ["request_id", "target", "vulnerability", "severity", "evidence_log"],
        },
    },
    {
        "name": "generate_proof_of_concept",
        "description": (
            "Cria um PoC mínimo e seguro (script bash comentado) para demonstrar a vulnerabilidade "
            "sem executar payloads destrutivos. Apenas para fins de documentação."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "vulnerability_type": {
                    "type": "string",
                    "description": "Tipo: rbac_escalation | secret_exposure | network_lateral_movement | outro",
                },
                "target": {"type": "string", "description": "Recurso alvo"},
                "evidence": {"type": "string", "description": "Resumo da evidência coletada"},
            },
            "required": ["request_id", "vulnerability_type", "target", "evidence"],
        },
    },
    {
        "name": "archive_to_metatron",
        "description": (
            "Envia relatório e artefatos do pentest ao Metatron para arquivamento permanente. "
            "Retorna referência de arquivo rastreável com request_id."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "request_id": {"type": "string"},
                "report_content": {
                    "type": "string",
                    "description": "Conteúdo completo do relatório a arquivar",
                },
                "vulnerability": {"type": "string"},
                "severity": {"type": "string"},
                "cvss_score": {"type": "number"},
            },
            "required": ["request_id", "report_content", "vulnerability", "severity"],
        },
    },
]


# ─────────────────────────────────────────────────────────────────
# dispatcher
# ─────────────────────────────────────────────────────────────────

async def execute_tool(tool_name: str, tool_input: dict) -> Any:
    """Despacha chamadas de tools pelo nome."""
    dispatchers = {
        "confirm_rbac_escalation": confirm_rbac_escalation,
        "test_secret_exposure": test_secret_exposure,
        "scan_network_reachability": scan_network_reachability,
        "check_api_server_exposure": check_api_server_exposure,
        "generate_pentest_report": generate_pentest_report,
        "generate_proof_of_concept": generate_proof_of_concept,
        "archive_to_metatron": archive_to_metatron,
    }
    fn = dispatchers.get(tool_name)
    if fn is None:
        return {"error": f"Tool '{tool_name}' não existe no Zerocool"}
    try:
        return await fn(**tool_input)
    except Exception as e:
        log.error("Zerocool: erro ao executar tool", tool=tool_name, error=str(e))
        return {"error": str(e), "tool": tool_name}
