import React, { useState } from "react";
import { AgentName, AgentStatus as AgentStatusType } from "../types";

const AGENT_COLORS: Record<AgentName, string> = {
  Metatron: "#7c3aed",
  Beholder: "#0ea5e9",
  LogicX:   "#10b981",
  Vops:     "#f59e0b",
  CyberT:   "#ef4444",
  Zerocool: "#ec4899",
  system:   "#6b7280",
};

const AGENT_EMOJI_FALLBACK: Record<AgentName, string> = {
  Metatron: "📜",
  Beholder: "👁️",
  LogicX:   "🧠",
  Vops:     "⚙️",
  CyberT:   "🛡️",
  Zerocool: "💻",
  system:   "🔧",
};

const AGENT_PHOTO: Record<string, string> = {
  Metatron: "/agents/metatron.png",
  Beholder: "/agents/beholder.png",
  LogicX:   "/agents/logicx.png",
  Vops:     "/agents/vops.png",
  CyberT:   "/agents/cybert.png",
  Zerocool: "/agents/zerocool.png",
};

interface Props {
  agents: AgentStatusType[];
  activeAgent?: AgentName;
}

export function AgentStatusPanel({ agents, activeAgent }: Props) {
  return (
    <div style={{
      display: "flex",
      flexDirection: "column",
      gap: "6px",
      padding: "16px",
      background: "#111827",
      borderRight: "1px solid #1f2937",
      width: "220px",
      minHeight: "100vh",
    }}>
      <div style={{
        color: "#9ca3af",
        fontSize: "11px",
        fontWeight: 600,
        letterSpacing: "0.1em",
        marginBottom: "10px",
      }}>
        AGENTES
      </div>
      {agents.map((agent) => (
        <AgentCard
          key={agent.name}
          agent={agent}
          isActive={activeAgent === agent.name}
        />
      ))}
    </div>
  );
}

function AgentAvatar({
  name,
  color,
  isOnline,
  size = 36,
}: {
  name: string;
  color: string;
  isOnline: boolean;
  size?: number;
}) {
  const [imgError, setImgError] = useState(false);
  const photoSrc = AGENT_PHOTO[name];
  const fallback = AGENT_EMOJI_FALLBACK[name as AgentName] ?? "🤖";

  return (
    <div style={{
      position: "relative",
      width: size,
      height: size,
      flexShrink: 0,
    }}>
      <div style={{
        width: size,
        height: size,
        borderRadius: "8px",
        overflow: "hidden",
        border: `2px solid ${isOnline ? color : "#374151"}`,
        background: `${color}22`,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        filter: isOnline ? "none" : "grayscale(80%) opacity(0.5)",
        transition: "filter 0.3s ease",
      }}>
        {photoSrc && !imgError ? (
          <img
            src={photoSrc}
            alt={name}
            onError={() => setImgError(true)}
            style={{
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: "center top",
            }}
          />
        ) : (
          <span style={{ fontSize: size * 0.45 }}>{fallback}</span>
        )}
      </div>

      {/* Indicador online/offline sobre a foto */}
      <div style={{
        position: "absolute",
        bottom: "-2px",
        right: "-2px",
        width: "10px",
        height: "10px",
        borderRadius: "50%",
        background: isOnline ? "#10b981" : "#374151",
        border: "2px solid #111827",
        boxShadow: isOnline ? "0 0 6px #10b981" : "none",
      }} />
    </div>
  );
}

function AgentCard({ agent, isActive }: { agent: AgentStatusType; isActive: boolean }) {
  const color = AGENT_COLORS[agent.name] || "#6b7280";
  const isOnline = agent.status === "online";

  return (
    <div style={{
      padding: "8px 10px",
      borderRadius: "10px",
      background: isActive ? `${color}22` : "#1f2937",
      border: `1px solid ${isActive ? color : "#374151"}`,
      transition: "all 0.2s ease",
      boxShadow: isActive ? `0 0 12px ${color}33` : "none",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
        <AgentAvatar name={agent.name} color={color} isOnline={isOnline} size={36} />
        <div style={{ flex: 1, overflow: "hidden" }}>
          <div style={{
            color: isOnline ? color : "#6b7280",
            fontWeight: 600,
            fontSize: "13px",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}>
            {agent.name}
          </div>
          <div style={{
            color: "#4b5563",
            fontSize: "10px",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}>
            {agent.role}
          </div>
        </div>
      </div>
    </div>
  );
}
