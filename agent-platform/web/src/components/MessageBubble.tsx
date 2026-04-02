import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AgentName, ChatMessage } from "../types";
import { FileAttachment } from "./FileAttachment";
import { FeedbackButtons } from "./FeedbackButtons";

const AGENT_COLORS: Record<string, string> = {
  Metatron: "#7c3aed",
  Beholder: "#0ea5e9",
  LogicX:   "#10b981",
  Vops:     "#f59e0b",
  CyberT:   "#ef4444",
  Zerocool: "#ec4899",
  system:   "#6b7280",
};

// Emoji de fallback caso a imagem não carregue
const AGENT_EMOJI_FALLBACK: Record<string, string> = {
  Metatron: "📜",
  Beholder: "👁️",
  LogicX:   "🧠",
  Vops:     "⚙️",
  CyberT:   "🛡️",
  Zerocool: "💻",
  system:   "🔧",
};

// Mapeia nome do agente para arquivo de foto em /agents/
const AGENT_PHOTO: Record<string, string> = {
  Metatron: "/agents/metatron.png",
  Beholder: "/agents/beholder.png",
  LogicX:   "/agents/logicx.png",
  Vops:     "/agents/vops.png",
  CyberT:   "/agents/cybert.png",
  Zerocool: "/agents/zerocool.png",
};

interface Props {
  message: ChatMessage;
  sessionId?: string;
  onFeedback?: (messageId: string, rating: "positive" | "negative") => void;
}

function AgentAvatar({ agentName, color }: { agentName: string; color: string }) {
  const [imgError, setImgError] = useState(false);
  const photoSrc = AGENT_PHOTO[agentName];
  const fallback = AGENT_EMOJI_FALLBACK[agentName] ?? "🤖";

  return (
    <div style={{
      width: "40px",
      height: "40px",
      borderRadius: "10px",
      border: `2px solid ${color}`,
      overflow: "hidden",
      flexShrink: 0,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: `${color}22`,
      boxShadow: `0 0 8px ${color}44`,
    }}>
      {photoSrc && !imgError ? (
        <img
          src={photoSrc}
          alt={agentName}
          onError={() => setImgError(true)}
          style={{
            width: "100%",
            height: "100%",
            objectFit: "cover",
            objectPosition: "center top",
          }}
        />
      ) : (
        <span style={{ fontSize: "18px" }}>{fallback}</span>
      )}
    </div>
  );
}

export function MessageBubble({ message, sessionId, onFeedback }: Props) {
  const isUser = message.role === "user";
  const agentColor = message.agent ? (AGENT_COLORS[message.agent] ?? "#6b7280") : "#6b7280";

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
      {/* Avatar com foto do agente */}
      <AgentAvatar agentName={message.agent || "system"} color={agentColor} />

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
                // Todos os links abrem em nova aba — evita recarregar o SPA
                a: ({ href, children }) => (
                  <a
                    href={href}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{ color: "#7c3aed", textDecoration: "underline" }}
                  >
                    {children}
                  </a>
                ),
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

        {/* Anexos de arquivo (Metatron) */}
        {message.files && message.files.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: "8px", marginTop: "8px" }}>
            {message.files.map((f) => (
              <FileAttachment key={f.filename} file={f} />
            ))}
          </div>
        )}

        {/* Timestamp + Feedback */}
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginTop: "4px" }}>
          <div style={{ color: "#4b5563", fontSize: "11px" }}>
            {new Date(message.timestamp).toLocaleTimeString("pt-BR")}
          </div>
          {!message.isStreaming && message.messageId && sessionId && onFeedback && (
            <FeedbackButtons
              messageId={message.messageId}
              sessionId={sessionId}
              agent={message.agent ?? "system"}
              currentFeedback={message.feedback}
              onFeedback={onFeedback}
            />
          )}
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
