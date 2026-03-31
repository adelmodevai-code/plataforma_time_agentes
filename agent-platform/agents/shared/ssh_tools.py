"""
SSH Tools — execução remota de comandos via SSH.

Módulo compartilhado usado por Beholder, CyberT, LogicX, Vops e Zerocool.
Cada agente importa SSH_TOOL_DEFINITION e execute_ssh_command daqui.

Autenticação suportada:
  - Chave privada (caminho para arquivo montado no container)
  - Senha
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger(__name__)

SSH_TIMEOUT = 30  # segundos por comando

# ─── Definição de tool para a Claude API ─────────────────────────────────────

SSH_TOOL_DEFINITION = {
    "name": "run_ssh_command",
    "description": (
        "Executa um comando em um servidor remoto via SSH. "
        "Use para inspecionar sistemas Linux, coletar logs, verificar processos, "
        "checar configurações ou executar diagnósticos em servidores reais. "
        "Suporta autenticação por chave privada (recomendado) ou senha."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "host": {
                "type": "string",
                "description": "Hostname ou IP do servidor destino.",
            },
            "port": {
                "type": "integer",
                "description": "Porta SSH (default: 22).",
                "default": 22,
            },
            "username": {
                "type": "string",
                "description": "Usuário SSH para autenticação.",
            },
            "command": {
                "type": "string",
                "description": (
                    "Comando shell a ser executado no servidor remoto. "
                    "Ex: 'uptime', 'df -h', 'journalctl -n 50 --no-pager', 'ps aux | grep nginx'"
                ),
            },
            "private_key_path": {
                "type": "string",
                "description": (
                    "Caminho absoluto para o arquivo de chave privada SSH no container. "
                    "Ex: '/run/secrets/ssh_key' ou '/home/app/.ssh/id_rsa'. "
                    "Preferível à senha."
                ),
            },
            "password": {
                "type": "string",
                "description": (
                    "Senha SSH. Use apenas se chave privada não estiver disponível. "
                    "Nunca envie senhas de produção — prefira chaves."
                ),
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout do comando em segundos (default: 30, máx: 120).",
                "default": 30,
            },
        },
        "required": ["host", "username", "command"],
    },
}


# ─── Implementação ────────────────────────────────────────────────────────────

async def execute_ssh_command(
    host: str,
    username: str,
    command: str,
    port: int = 22,
    private_key_path: str | None = None,
    password: str | None = None,
    timeout: int = SSH_TIMEOUT,
) -> dict[str, Any]:
    """
    Conecta ao host via SSH e executa o comando.

    Retorna dict com:
      - stdout: saída padrão
      - stderr: saída de erro
      - exit_code: código de saída do processo
      - host / command / timestamp: contexto da execução
      - error: presente apenas em caso de falha de conexão ou timeout
    """
    timeout = min(timeout, 120)  # cap máximo de 120s

    try:
        import asyncssh  # type: ignore[import]
    except ImportError:
        return {
            "error": "asyncssh não instalado. Adicione 'asyncssh' ao requirements.txt.",
            "host": host,
            "command": command,
        }

    connect_kwargs: dict[str, Any] = {
        "host": host,
        "port": port,
        "username": username,
        "known_hosts": None,  # aceita qualquer host key (ambiente controlado)
        "connect_timeout": 10,
    }

    if private_key_path:
        connect_kwargs["client_keys"] = [private_key_path]
        connect_kwargs["passphrase"] = None
    elif password:
        connect_kwargs["password"] = password
    else:
        return {
            "error": "Forneça 'private_key_path' ou 'password' para autenticar.",
            "host": host,
            "command": command,
        }

    log.info("SSH: conectando", host=host, port=port, username=username)

    try:
        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await asyncio.wait_for(
                conn.run(command, check=False),
                timeout=timeout,
            )

        stdout = (result.stdout or "").strip()
        stderr = (result.stderr or "").strip()
        exit_code = result.exit_status if result.exit_status is not None else -1

        log.info(
            "SSH: comando executado",
            host=host,
            exit_code=exit_code,
            stdout_len=len(stdout),
        )

        return {
            "host": host,
            "username": username,
            "command": command,
            "exit_code": exit_code,
            "stdout": stdout[:8000] if stdout else "",   # trunca saída muito grande
            "stderr": stderr[:2000] if stderr else "",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    except asyncio.TimeoutError:
        log.warning("SSH: timeout", host=host, command=command, timeout=timeout)
        return {
            "error": f"Timeout após {timeout}s executando o comando.",
            "host": host,
            "command": command,
        }
    except Exception as exc:
        log.error("SSH: falha na conexão", host=host, error=str(exc))
        return {
            "error": f"Falha SSH: {exc}",
            "host": host,
            "command": command,
        }
