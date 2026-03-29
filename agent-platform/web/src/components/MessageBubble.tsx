import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AgentName, ChatMessage } from "../types";

const AGENT_COLORS: Record<string, string> = {
  Metatron: "#7c3aed",
  Beholder: "#0ea5e9",
  LogicX: "#10b981",
  Vops: "#f59e0b",
  CyberT: "#ef4444",
  Zerocool: "#ec4899",
  system: "#6b7280",
};

const AGENT_ICONS: Record<string, string> = {
  Metatron: "📜",
  Beholder: "👁️",
  LogicX: "🧠",
  Vops: "⚙️",
  CyberT: "🛡️",
  Zerocool: "💻",
  system: "🔧",
};

interface Props {
  message: ChatMessage;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";
  const agentColor = message.agent ? (AGENT_COLORS[message.agent] ?? "#6b7280") : "#6b7280";
  const agentIcon = message.agent ? (AGENT_ICONS[message.agent] ?? "🤖") : "🤖";

  if (isUser) {
    return (
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: "16px" }}>
        <div style={{
          maxWidth: "70%",
          padding: "12px 16px",
          background: "#2563eb",
          borderRadius: "16px 16px 4px 16px",
          color: "#fff",
          fontSize: "14px",
          lineHeight: "1.5",
        }}>
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: "12px", marginBottom: "16px", alignItems: "flex-start" }}>
      {/* Avatar do Agente */}
      <div style={{
        width: "36px",
        height: "36px",
        borderRadius: "10px",
        background: `${agentColor}22`,
        border: `1px solid ${agentColor}`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontSize: "16px",
        flexShrink: 0,
      }}>
        {agentIcon}
      </div>

      <div style={{ flex: 1, maxWidth: "80%" }}>
        {/* Nome do Agente */}
        <div style={{
          color: agentColor,
          fontSize: "12px",
          fontWeight: 600,
          marginBottom: "4px",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
        }}>
          {message.agent || "System"}
        </div>

        {/* Conteúdo */}
        <div style={{
          padding: "12px 16px",
          background: "#1f2937",
          borderRadius: "4px 16px 16px 16px",
          border: `1px solid #374151`,
          color: "#e5e7eb",
          fontSize: "14px",
          lineHeight: "1.6",
        }}>
          {message.isStreaming && message.content === "" ? (
            <TypingIndicator color={agentColor} />
          ) : (
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code: ({ node, className, children, ...props }) => {
                  const isBlock = className?.includes("language-");
                  return isBlock ? (
                    <pre style={{
                      background: "#111827",
                      padding: "12px",
                      borderRadius: "6px",
                      overflowX: "auto",
                      fontSize: "13px",
                    }}>
                      <code style={{ color: "#a5f3fc" }}>{children}</code>
                    </pre>
                  ) : (
                    <code style={{
                      background: "#111827",
                      padding: "2px 6px",
                      borderRadius: "4px",
                      color: "#a5f3fc",
                      fontSize: "13px",
                    }}>
                      {children}
                    </code>
                  );
                },
                table: ({ children }) => (
                  <div style={{ overflowX: "auto" }}>
                    <table style={{
                      borderCollapse: "collapse",
                      width: "100%",
                      fontSize: "13px",
                    }}>{children}</table>
                  </div>
                ),
                th: ({ children }) => (
                  <th style={{
                    padding: "8px 12px",
                    background: "#111827",
                    border: "1px solid #374151",
                    color: "#9ca3af",
                    textAlign: "left",
                  }}>{children}</th>
                ),
                td: ({ children }) => (
                  <td style={{
                    padding: "8px 12px",
                    border: "1px solid #374151",
                    color: "#e5e7eb",
                  }}>{children}</td>
                ),
              }}
            >
              {message.content}
            </ReactMarkdown>
          )}
          {message.isStreaming && message.content !== "" && (
            <span style={{
              display: "inline-block",
              width: "6px",
              height: "14px",
              background: agentColor,
              marginLeft: "2px",
              animation: "blink 1s step-end infinite",
            }} />
          )}
        </div>

        {/* Timestamp */}
        <div style={{ color: "#4b5563", fontSize: "11px", marginTop: "4px" }}>
          {new Date(message.timestamp).toLocaleTimeString("pt-BR")}
        </div>
      </div>
    </div>
  );
}

function TypingIndicator({ color }: { color: string }) {
  return (
    <div style={{ display: "flex", gap: "4px", alignItems: "center", padding: "4px 0" }}>
      {[0, 1, 2].map((i) => (
        <div key={i} style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: color,
          animation: `typing-bounce 1.2s ease-in-out ${i * 0.2}s infinite`,
        }} />
      ))}
    </div>
  );
}
