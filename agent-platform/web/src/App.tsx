/// <reference types="vite/client" />
import React, { useCallback, useEffect, useRef, useState } from "react";
import { AgentEvent, AgentName, AgentStatus, ApprovalRequest, ChatMessage } from "./types";
import { useWebSocket } from "./hooks/useWebSocket";
import { AgentStatusPanel } from "./components/AgentStatus";
import { MessageBubble } from "./components/MessageBubble";

const WS_URL = (import.meta as ImportMeta & { env: Record<string, string> }).env?.VITE_WS_URL ?? "ws://localhost:8080/ws";
const API_URL = (import.meta as ImportMeta & { env: Record<string, string> }).env?.VITE_API_URL ?? "http://localhost:8080";

const INITIAL_AGENTS: AgentStatus[] = [
  { name: "Beholder",  status: "online",  role: "Observabilidade e sentinela", phase: 1 },
  { name: "Metatron",  status: "online",  role: "Documentação (sob demanda)",  phase: 1 },
  { name: "LogicX",   status: "online",  role: "Análise e decisão",            phase: 3 },
  { name: "Vops",     status: "online",  role: "Infraestrutura k8s",           phase: 3 },
  { name: "CyberT",   status: "offline", role: "Segurança",                    phase: 4 },
  { name: "Zerocool", status: "offline", role: "Pentesting autorizado",        phase: 4 },
];

export default function App() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [agents, setAgents] = useState<AgentStatus[]>(INITIAL_AGENTS);
  const [activeAgent, setActiveAgent] = useState<AgentName | undefined>("Beholder");
  const [sessionId, setSessionId] = useState<string>("");
  const [input, setInput] = useState("");
  const [pendingApproval, setPendingApproval] = useState<ApprovalRequest | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const streamingMessageRef = useRef<string | null>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(scrollToBottom, [messages]);

  const handleEvent = useCallback((event: AgentEvent) => {
    const agentName = event.agent as AgentName;

    if (event.type === "typing") {
      setActiveAgent(agentName);
      const typingId = `typing-${event.message_id}`;
      streamingMessageRef.current = typingId;
      setMessages((prev) => [
        ...prev.filter((m) => m.id !== typingId),
        {
          id: typingId,
          role: "agent",
          agent: agentName,
          content: "",
          timestamp: new Date().toISOString(),
          isStreaming: true,
        },
      ]);
      return;
    }

    if (event.type === "message") {
      const streamId = streamingMessageRef.current;
      setMessages((prev) => {
        if (streamId && prev.some((m) => m.id === streamId)) {
          return prev.map((m) =>
            m.id === streamId
              ? { ...m, content: m.content + event.content, isStreaming: true }
              : m
          );
        }
        return [
          ...prev,
          {
            id: event.message_id + "-" + Date.now(),
            role: "agent",
            agent: agentName,
            content: event.content,
            timestamp: event.timestamp || new Date().toISOString(),
            isStreaming: false,
          },
        ];
      });
      return;
    }

    if (event.type === "complete") {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === streamingMessageRef.current ? { ...m, isStreaming: false } : m
        )
      );
      streamingMessageRef.current = null;
      return;
    }

    if (event.type === "action") {
      setMessages((prev) => [
        ...prev,
        {
          id: event.message_id + "-action-" + Date.now(),
          role: "agent",
          agent: agentName,
          content: `🔧 **Ação:** ${event.content}`,
          timestamp: event.timestamp || new Date().toISOString(),
        },
      ]);
      return;
    }

    if (event.type === "approval_request") {
      setPendingApproval(event.metadata as unknown as ApprovalRequest);
      setMessages((prev) => [
        ...prev,
        {
          id: event.message_id + "-approval",
          role: "agent",
          agent: agentName,
          content: `⚠️ **Zerocool solicita autorização para pentest.** Veja o painel de aprovação.`,
          timestamp: event.timestamp || new Date().toISOString(),
        },
      ]);
      return;
    }

    if (event.type === "error") {
      setMessages((prev) => [
        ...prev,
        {
          id: event.message_id + "-error",
          role: "agent",
          agent: agentName,
          content: `❌ ${event.content}`,
          timestamp: event.timestamp || new Date().toISOString(),
        },
      ]);
      return;
    }
  }, []);

  const handleSessionId = useCallback((id: string) => {
    setSessionId(id);
    setMessages([{
      id: "welcome",
      role: "agent",
      agent: "Beholder",
      content: `👁️ **Beholder online.**\n\nOlá, Adelmo. Estou monitorando o ambiente.\n\n**Status atual — Fase 1 (modo conversacional):**\n- Stack de observabilidade: *aguardando Fase 2*\n- Cluster k8s: Docker Desktop (1 nó ativo)\n- Agentes ativos: **Beholder** (eu) + **Metatron** (documentação sob demanda)\n\nQuando Prometheus e Loki estiverem conectados, reportarei métricas em tempo real. Por agora, me diga o que precisa observar. 🔭\n\n**Sessão:** \`${id}\``,
      timestamp: new Date().toISOString(),
    }]);
  }, []);

  const { status, send } = useWebSocket({
    url: WS_URL,
    onEvent: handleEvent,
    onSessionId: handleSessionId,
  });

  const sendMessage = useCallback(() => {
    const content = input.trim();
    if (!content || status !== "connected") return;

    const messageId = crypto.randomUUID();

    setMessages((prev) => [
      ...prev,
      {
        id: messageId,
        role: "user",
        content,
        timestamp: new Date().toISOString(),
      },
    ]);

    send({
      type: "user_message",
      message_id: messageId,
      content,
    });

    setInput("");
  }, [input, status, send]);

  const handleApproval = useCallback((approved: boolean) => {
    if (!pendingApproval) return;
    send({
      type: approved ? "approval" : "denial",
      message_id: crypto.randomUUID(),
      content: approved ? "Autorizado" : "Negado",
      metadata: { request_id: pendingApproval.request_id },
    });
    setPendingApproval(null);
  }, [pendingApproval, send]);

  return (
    <div style={{ display: "flex", height: "100vh", background: "#0f172a", fontFamily: "system-ui, sans-serif" }}>
      <style>{`
        * { box-sizing: border-box; margin: 0; padding: 0; }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes typing-bounce {
          0%, 60%, 100% { transform: translateY(0); }
          30% { transform: translateY(-6px); }
        }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-track { background: #111827; }
        ::-webkit-scrollbar-thumb { background: #374151; border-radius: 3px; }
      `}</style>

      {/* Sidebar de Agentes */}
      <AgentStatusPanel agents={agents} activeAgent={activeAgent} />

      {/* Área principal */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        {/* Header */}
        <div style={{
          padding: "16px 24px",
          borderBottom: "1px solid #1f2937",
          display: "flex",
          alignItems: "center",
          gap: "12px",
          background: "#111827",
        }}>
          <div>
            <div style={{ color: "#f9fafb", fontWeight: 700, fontSize: "16px" }}>
              Agent Platform
            </div>
            <div style={{ color: "#6b7280", fontSize: "12px" }}>
              {sessionId ? `Sessão: ${sessionId.slice(0, 8)}...` : "Conectando..."}
            </div>
          </div>
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "8px" }}>
            <div style={{
              width: "8px", height: "8px", borderRadius: "50%",
              background: status === "connected" ? "#10b981" : status === "connecting" ? "#f59e0b" : "#ef4444",
              boxShadow: status === "connected" ? "0 0 6px #10b981" : "none",
            }} />
            <span style={{ color: "#6b7280", fontSize: "12px" }}>
              {status === "connected" ? "Conectado" : status === "connecting" ? "Conectando..." : "Desconectado"}
            </span>
          </div>
        </div>

        {/* Modal de Aprovação Zerocool */}
        {pendingApproval && (
          <div style={{
            position: "fixed", inset: 0, background: "rgba(0,0,0,0.7)",
            display: "flex", alignItems: "center", justifyContent: "center", zIndex: 100,
          }}>
            <div style={{
              background: "#1f2937", borderRadius: "16px", padding: "32px",
              maxWidth: "480px", width: "90%", border: "1px solid #ec4899",
            }}>
              <div style={{ color: "#ec4899", fontWeight: 700, fontSize: "18px", marginBottom: "8px" }}>
                💻 Zerocool — Autorização de Pentest
              </div>
              <div style={{ color: "#9ca3af", fontSize: "13px", marginBottom: "16px" }}>
                {pendingApproval.description}
              </div>
              <div style={{ display: "flex", flexDirection: "column", gap: "8px", marginBottom: "24px" }}>
                {[
                  ["Alvo", pendingApproval.target],
                  ["Tipo de Teste", pendingApproval.test_type],
                  ["Vulnerabilidade", pendingApproval.vulnerability],
                  ["Risco", pendingApproval.risk_level.toUpperCase()],
                ].map(([label, value]) => (
                  <div key={label} style={{ display: "flex", gap: "8px" }}>
                    <span style={{ color: "#6b7280", fontSize: "12px", width: "120px" }}>{label}:</span>
                    <span style={{ color: "#e5e7eb", fontSize: "12px" }}>{value}</span>
                  </div>
                ))}
              </div>
              <div style={{ display: "flex", gap: "12px" }}>
                <button onClick={() => handleApproval(true)} style={{
                  flex: 1, padding: "10px", background: "#10b981", color: "#fff",
                  border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: 600,
                }}>
                  ✅ Autorizar
                </button>
                <button onClick={() => handleApproval(false)} style={{
                  flex: 1, padding: "10px", background: "#374151", color: "#9ca3af",
                  border: "none", borderRadius: "8px", cursor: "pointer", fontWeight: 600,
                }}>
                  ❌ Negar
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Feed de mensagens */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
          {messages.map((msg) => (
            <MessageBubble key={msg.id} message={msg} />
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div style={{
          padding: "16px 24px",
          borderTop: "1px solid #1f2937",
          background: "#111827",
          display: "flex",
          gap: "12px",
        }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
            placeholder="Fale com os agentes..."
            disabled={status !== "connected"}
            style={{
              flex: 1, padding: "12px 16px",
              background: "#1f2937", border: "1px solid #374151",
              borderRadius: "10px", color: "#f9fafb", fontSize: "14px",
              outline: "none",
            }}
          />
          <button
            onClick={sendMessage}
            disabled={status !== "connected" || !input.trim()}
            style={{
              padding: "12px 24px",
              background: status === "connected" && input.trim() ? "#2563eb" : "#1f2937",
              color: status === "connected" && input.trim() ? "#fff" : "#4b5563",
              border: "none", borderRadius: "10px",
              cursor: status === "connected" && input.trim() ? "pointer" : "not-allowed",
              fontWeight: 600, fontSize: "14px", transition: "all 0.2s",
            }}
          >
            Enviar
          </button>
        </div>
      </div>
    </div>
  );
}
