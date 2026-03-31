"""
CyberT Tools — auditoria de segurança do cluster Kubernetes.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from agents.shared.ssh_tools import SSH_TOOL_DEFINITION, execute_ssh_command

log = structlog.get_logger(__name__)

_k8s_core = None
_k8s_apps = None
_k8s_rbac = None
_k8s_net = None
_k8s_loaded = False


def _load_k8s():
    global _k8s_core, _k8s_apps, _k8s_rbac, _k8s_net, _k8s_loaded
    if _k8s_loaded:
        return
    try:
        from kubernetes import client, config
        try:
            config.load_incluster_config()
        except Exception:
            config.load_kube_config()
        _k8s_core = client.CoreV1Api()
        _k8s_apps = client.AppsV1Api()
        _k8s_rbac = client.RbacAuthorizationV1Api()
        _k8s_net = client.NetworkingV1Api()
        _k8s_loaded = True
    except Exception as e:
        log.error("CyberT: falha ao carregar k8s client", error=str(e))


TOOL_DEFINITIONS = [
    {
        "name": "audit_rbac",
        "description": "Audita permissões RBAC excessivas: ClusterRoles com wildcard, bindings para serviceaccounts desnecessários.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "Namespace específico (omitir para cluster-wide)"},
            },
        },
    },
    {
        "name": "check_pod_security",
        "description": "Verifica contextos de segurança dos pods: privilegiado, runAsRoot, hostNetwork, hostPID, capabilities perigosas.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "Namespace para auditar (omitir para todos)"},
            },
        },
    },
    {
        "name": "scan_exposed_secrets",
        "description": "Detecta segredos potencialmente expostos em variáveis de ambiente e ConfigMaps.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
            },
        },
    },
    {
        "name": "check_network_policies",
        "description": "Identifica namespaces e pods sem NetworkPolicy (totalmente expostos na rede interna do cluster).",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
            },
        },
    },
    {
        "name": "audit_image_security",
        "description": "Audita imagens de containers: uso de :latest, ausência de digest, registries não confiáveis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
            },
        },
    },
    {
        "name": "check_service_exposure",
        "description": "Lista serviços NodePort e LoadBalancer expostos externamente, avaliando risco de exposição.",
        "input_schema": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
            },
        },
    },
    SSH_TOOL_DEFINITION,
    {
        "name": "request_pentest_authorization",
        "description": (
            "Solicita autorização do Adelmo para o Zerocool confirmar uma vulnerabilidade via pentest. "
            "Use apenas para achados CRÍTICO ou ALTO já documentados."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "vulnerability": {"type": "string", "description": "Vulnerabilidade identificada"},
                "target": {"type": "string", "description": "Alvo do pentest (pod/service/endpoint)"},
                "test_type": {"type": "string", "description": "Tipo de teste: port_scan, service_probe, auth_test, config_check"},
                "risk_level": {"type": "string", "enum": ["low", "medium", "high"], "description": "Risco estimado da execução do teste"},
                "description": {"type": "string", "description": "Descrição detalhada do que o Zerocool fará"},
            },
            "required": ["vulnerability", "target", "test_type", "risk_level", "description"],
        },
    },
]


async def audit_rbac(namespace: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "k8s client não disponível"}

    findings = []
    try:
        # ClusterRoles com wildcards (*)
        cluster_roles = _k8s_rbac.list_cluster_role()
        for cr in cluster_roles.items:
            wildcards = []
            for rule in (cr.rules or []):
                if "*" in (rule.verbs or []) or "*" in (rule.resources or []):
                    wildcards.append({
                        "verbs": rule.verbs,
                        "resources": rule.resources,
                        "api_groups": rule.api_groups,
                    })
            if wildcards and cr.metadata.name not in ["cluster-admin", "admin", "edit", "view"]:
                findings.append({
                    "type": "wildcard_clusterrole",
                    "severity": "🟠 ALTO",
                    "resource": f"ClusterRole/{cr.metadata.name}",
                    "detail": f"{len(wildcards)} regra(s) com wildcard",
                    "rules": wildcards[:3],
                    "remediation": f"Revise e restrinja as permissões de ClusterRole/{cr.metadata.name}",
                })

        # ClusterRoleBindings para serviceaccounts default
        crbs = _k8s_rbac.list_cluster_role_binding()
        for crb in crbs.items:
            for subject in (crb.subjects or []):
                if subject.kind == "ServiceAccount" and subject.name == "default":
                    findings.append({
                        "type": "default_sa_binding",
                        "severity": "🟡 MÉDIO",
                        "resource": f"ClusterRoleBinding/{crb.metadata.name}",
                        "detail": f"ServiceAccount 'default' no namespace '{subject.namespace}' tem binding para '{crb.role_ref.name}'",
                        "remediation": "Crie ServiceAccounts dedicadas com permissões mínimas",
                    })

        # RoleBindings no namespace especificado
        if namespace:
            rbs = _k8s_rbac.list_namespaced_role_binding(namespace)
            for rb in rbs.items:
                for subject in (rb.subjects or []):
                    if subject.kind == "ServiceAccount" and subject.name == "default":
                        findings.append({
                            "type": "default_sa_role_binding",
                            "severity": "🟡 MÉDIO",
                            "resource": f"RoleBinding/{rb.metadata.name}",
                            "namespace": namespace,
                            "detail": f"ServiceAccount 'default' com role '{rb.role_ref.name}'",
                            "remediation": "Use ServiceAccounts dedicadas",
                        })

    except Exception as e:
        return {"error": str(e)}

    return {
        "audit": "rbac",
        "namespace": namespace or "cluster-wide",
        "total_findings": len(findings),
        "findings": findings,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def check_pod_security(namespace: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "k8s client não disponível"}

    findings = []
    try:
        if namespace:
            pods = _k8s_core.list_namespaced_pod(namespace)
        else:
            pods = _k8s_core.list_pod_for_all_namespaces()

        for pod in pods.items:
            ns = pod.metadata.namespace
            name = pod.metadata.name
            spec = pod.spec

            # hostNetwork / hostPID / hostIPC
            if spec.host_network:
                findings.append({"severity": "🔴 CRÍTICO", "pod": name, "namespace": ns,
                                  "issue": "hostNetwork: true — acesso direto à rede do host",
                                  "remediation": "Remova hostNetwork: true do spec do pod"})
            if spec.host_pid:
                findings.append({"severity": "🔴 CRÍTICO", "pod": name, "namespace": ns,
                                  "issue": "hostPID: true — acesso ao namespace de PID do host",
                                  "remediation": "Remova hostPID: true"})

            for container in (spec.containers or []):
                sc = container.security_context
                if not sc:
                    findings.append({"severity": "🟡 MÉDIO", "pod": name, "namespace": ns,
                                      "container": container.name,
                                      "issue": "Sem securityContext definido",
                                      "remediation": "Adicione securityContext com runAsNonRoot: true e readOnlyRootFilesystem: true"})
                    continue

                if sc.privileged:
                    findings.append({"severity": "🔴 CRÍTICO", "pod": name, "namespace": ns,
                                      "container": container.name,
                                      "issue": "privileged: true — container com acesso total ao kernel",
                                      "remediation": "Remova privileged: true"})

                if sc.run_as_user == 0 or (sc.run_as_non_root is False):
                    findings.append({"severity": "🟠 ALTO", "pod": name, "namespace": ns,
                                      "container": container.name,
                                      "issue": "Container rodando como root (UID 0)",
                                      "remediation": "Defina runAsNonRoot: true e runAsUser com UID > 1000"})

                if sc.allow_privilege_escalation is not False:
                    findings.append({"severity": "🟡 MÉDIO", "pod": name, "namespace": ns,
                                      "container": container.name,
                                      "issue": "allowPrivilegeEscalation não desabilitado",
                                      "remediation": "Defina allowPrivilegeEscalation: false"})

                if sc.capabilities:
                    dangerous = {"SYS_ADMIN", "NET_ADMIN", "SYS_PTRACE", "DAC_OVERRIDE", "SETUID", "SETGID"}
                    caps = set(sc.capabilities.add or [])
                    found_dangerous = caps & dangerous
                    if found_dangerous:
                        findings.append({"severity": "🟠 ALTO", "pod": name, "namespace": ns,
                                          "container": container.name,
                                          "issue": f"Capabilities perigosas: {found_dangerous}",
                                          "remediation": "Remova as capabilities não necessárias"})

    except Exception as e:
        return {"error": str(e)}

    return {
        "audit": "pod_security",
        "namespace": namespace or "all",
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if "CRÍTICO" in f["severity"]),
        "high": sum(1 for f in findings if "ALTO" in f["severity"]),
        "medium": sum(1 for f in findings if "MÉDIO" in f["severity"]),
        "findings": findings,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def scan_exposed_secrets(namespace: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "k8s client não disponível"}

    # Padrões de variáveis que podem conter segredos
    SECRET_PATTERNS = {
        "api_key": ["api_key", "apikey", "api-key"],
        "password": ["password", "passwd", "pwd", "secret"],
        "token": ["token", "bearer", "auth"],
        "aws": ["aws_access_key", "aws_secret", "aws_session_token"],
        "database": ["db_pass", "database_url", "postgres_password", "mysql_password"],
        "anthropic": ["anthropic_api_key"],
    }

    findings = []
    try:
        namespaces = [namespace] if namespace else [
            n.metadata.name for n in _k8s_core.list_namespace().items
        ]

        for ns in namespaces:
            try:
                pods = _k8s_core.list_namespaced_pod(ns)
                for pod in pods.items:
                    for container in (pod.spec.containers or []):
                        for env in (container.env or []):
                            env_name_lower = (env.name or "").lower()
                            for category, patterns in SECRET_PATTERNS.items():
                                if any(p in env_name_lower for p in patterns):
                                    # Verifica se está usando valueFrom (seguro) ou value direto (inseguro)
                                    if env.value and not env.value_from:
                                        severity = "🔴 CRÍTICO" if category in ("anthropic", "aws", "database") else "🟠 ALTO"
                                        findings.append({
                                            "severity": severity,
                                            "namespace": ns,
                                            "pod": pod.metadata.name,
                                            "container": container.name,
                                            "env_var": env.name,
                                            "issue": f"Segredo '{category}' em valor direto (não via Secret k8s)",
                                            "value_hint": f"{env.value[:4]}***" if len(env.value) > 4 else "***",
                                            "remediation": "Mova para um Secret k8s e use valueFrom.secretKeyRef",
                                        })
                                    break  # evita duplicatas por categoria
            except Exception:
                continue

    except Exception as e:
        return {"error": str(e)}

    return {
        "audit": "exposed_secrets",
        "total_findings": len(findings),
        "critical": sum(1 for f in findings if "CRÍTICO" in f["severity"]),
        "findings": findings,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def check_network_policies(namespace: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "k8s client não disponível"}

    findings = []
    try:
        namespaces = [namespace] if namespace else [
            n.metadata.name for n in _k8s_core.list_namespace().items
            if n.metadata.name not in ("kube-system", "kube-public", "kube-node-lease")
        ]

        for ns in namespaces:
            try:
                policies = _k8s_net.list_namespaced_network_policy(ns)
                pods = _k8s_core.list_namespaced_pod(ns)
                policy_count = len(policies.items)
                pod_count = len([p for p in pods.items if p.status.phase == "Running"])

                if pod_count > 0 and policy_count == 0:
                    findings.append({
                        "severity": "🟠 ALTO",
                        "namespace": ns,
                        "issue": f"Namespace sem NetworkPolicy ({pod_count} pods rodando)",
                        "detail": "Todos os pods podem se comunicar livremente dentro do cluster",
                        "remediation": (
                            f"Crie uma NetworkPolicy default-deny em '{ns}' e "
                            "permita apenas tráfego necessário explicitamente"
                        ),
                    })
            except Exception:
                continue

    except Exception as e:
        return {"error": str(e)}

    return {
        "audit": "network_policies",
        "total_findings": len(findings),
        "findings": findings,
        "recommendation": "Implemente um default-deny por namespace e use NetworkPolicies para allowlist",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def audit_image_security(namespace: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "k8s client não disponível"}

    findings = []
    try:
        if namespace:
            pods = _k8s_core.list_namespaced_pod(namespace)
        else:
            pods = _k8s_core.list_pod_for_all_namespaces()

        seen_images: set[str] = set()
        for pod in pods.items:
            ns = pod.metadata.namespace
            for container in (pod.spec.containers or []):
                image = container.image or ""
                if image in seen_images:
                    continue
                seen_images.add(image)

                # Tag :latest ou sem tag
                if image.endswith(":latest") or (":" not in image.split("/")[-1]):
                    findings.append({
                        "severity": "🟡 MÉDIO",
                        "namespace": ns,
                        "pod": pod.metadata.name,
                        "container": container.name,
                        "image": image,
                        "issue": "Imagem usando tag ':latest' ou sem tag — builds não reproduzíveis",
                        "remediation": "Use tags semânticas (ex: v1.2.3) ou digest SHA256",
                    })

                # Registry não padrão (pode indicar imagem não verificada)
                if "/" in image and not any(
                    image.startswith(r)
                    for r in ("docker.io/", "gcr.io/", "ghcr.io/", "quay.io/", "registry.k8s.io/",
                              "prom/", "grafana/")
                ):
                    findings.append({
                        "severity": "🟡 MÉDIO",
                        "namespace": ns,
                        "image": image,
                        "issue": "Registry não verificado/não padrão",
                        "remediation": "Valide a proveniência da imagem e use um registry privado com scan de vulnerabilidades",
                    })

    except Exception as e:
        return {"error": str(e)}

    return {
        "audit": "image_security",
        "total_findings": len(findings),
        "findings": findings,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def check_service_exposure(namespace: str | None = None) -> dict:
    _load_k8s()
    if not _k8s_loaded:
        return {"error": "k8s client não disponível"}

    findings = []
    try:
        if namespace:
            services = _k8s_core.list_namespaced_service(namespace)
        else:
            services = _k8s_core.list_service_for_all_namespaces()

        for svc in services.items:
            ns = svc.metadata.namespace
            name = svc.metadata.name
            svc_type = svc.spec.type

            if svc_type == "NodePort":
                ports = [f"{p.port}:{p.node_port}" for p in (svc.spec.ports or []) if p.node_port]
                findings.append({
                    "severity": "🟡 MÉDIO",
                    "namespace": ns,
                    "service": name,
                    "type": "NodePort",
                    "ports": ports,
                    "issue": f"Serviço exposto via NodePort em todos os nós: {ports}",
                    "remediation": "Use Ingress com TLS em vez de NodePort para serviços de produção",
                })

            elif svc_type == "LoadBalancer":
                external_ip = (svc.status.load_balancer.ingress or [{}])[0].get("ip", "pending") if svc.status.load_balancer else "pending"
                findings.append({
                    "severity": "🟠 ALTO",
                    "namespace": ns,
                    "service": name,
                    "type": "LoadBalancer",
                    "external_ip": external_ip,
                    "issue": f"Serviço exposto diretamente na internet via LoadBalancer (IP: {external_ip})",
                    "remediation": "Verifique se a exposição é necessária; use Ingress + WAF quando possível",
                })

    except Exception as e:
        return {"error": str(e)}

    return {
        "audit": "service_exposure",
        "total_findings": len(findings),
        "findings": findings,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def request_pentest_authorization(
    vulnerability: str,
    target: str,
    test_type: str,
    risk_level: str,
    description: str,
) -> dict:
    """Prepara o pedido de autorização para Zerocool — emitido ao UI via evento approval_request."""
    request_id = str(uuid.uuid4())
    return {
        "approval_required": True,
        "request_id": request_id,
        "agent": "Zerocool",
        "vulnerability": vulnerability,
        "target": target,
        "test_type": test_type,
        "risk_level": risk_level,
        "description": description,
        "requested_by": "CyberT",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": (
            f"⚠️ **CyberT solicita autorização para pentest.**\n"
            f"Vulnerabilidade: **{vulnerability}**\n"
            f"Alvo: `{target}` | Tipo: `{test_type}` | Risco: `{risk_level.upper()}`\n"
            f"Zerocool aguarda sua aprovação, Adelmo."
        ),
    }


async def execute_tool(tool_name: str, tool_input: dict) -> Any:
    dispatch = {
        "audit_rbac": lambda i: audit_rbac(i.get("namespace")),
        "check_pod_security": lambda i: check_pod_security(i.get("namespace")),
        "scan_exposed_secrets": lambda i: scan_exposed_secrets(i.get("namespace")),
        "check_network_policies": lambda i: check_network_policies(i.get("namespace")),
        "audit_image_security": lambda i: audit_image_security(i.get("namespace")),
        "check_service_exposure": lambda i: check_service_exposure(i.get("namespace")),
        "request_pentest_authorization": lambda i: request_pentest_authorization(
            i["vulnerability"], i["target"], i["test_type"], i["risk_level"], i["description"]
        ),
        "run_ssh_command": lambda i: execute_ssh_command(
            i["host"], i["username"], i["command"],
            i.get("port", 22), i.get("private_key_path"), i.get("password"), i.get("timeout", 30),
        ),
    }
    fn = dispatch.get(tool_name)
    return await fn(tool_input) if fn else {"error": f"Tool desconhecida: {tool_name}"}
