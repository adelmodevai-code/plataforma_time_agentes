import React from "react";
import { AgentName, AgentStatus as AgentStatusType } from "../types";

const AGENT_COLORS: Record<AgentName, string> = {
  Metatron: "#7c3aed",
  Beholder: "#0ea5e9",
  LogicX: "#10b981",
  Vops: "#f59e0b",
  CyberT: "#ef4444",
  Zerocool: "#ec4899",
  system: "#6b7280",
};

const AGENT_ICONS: Record<AgentName, string> = {
  Metatron: "📜",
  Beholder: "👁️",
  LogicX: "🧠",
  Vops: "⚙️",
  CyberT: "🛡️",
  Zerocool: "💻",
  system: "🔧",
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
      gap: "8px",
      padding: "16px",
      background: "#111827",
      borderRight: "1px solid #1f2937",
      width: "220px",
      minHeight: "100vh",
    }}>
      <div style={{ color: "#9ca3af", fontSize: "11px", fontWeight: 600, letterSpacing: "0.1em", marginBottom: "8px" }}>
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

function AgentCard({ agent, isActive }: { agent: AgentStatusType; isActive: boolean }) {
  const color = AGENT_COLORS[agent.name] || "#6b7280";
  const icon = AGENT_ICONS[agent.name] || "🤖";
  const isOnline = agent.status === "online";

  return (
    <div style={{
      padding: "10px 12px",
      borderRadius: "8px",
      background: isActive ? `${color}22` : "#1f2937",
      border: `1px solid ${isActive ? color : "#374151"}`,
      transition: "all 0.2s ease",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
        <span style={{ fontSize: "16px" }}>{icon}</span>
        <div style={{ flex: 1 }}>
          <div style={{
            color: isOnline ? color : "#6b7280",
            fontWeight: 600,
            fontSize: "13px",
          }}>
            {agent.name}
          </div>
          <div style={{ color: "#6b7280", fontSize: "11px" }}>
            {agent.role}
          </div>
        </div>
        <div style={{
          width: "8px",
          height: "8px",
          borderRadius: "50%",
          background: isOnline ? "#10b981" : "#374151",
          boxShadow: isOnline ? "0 0 6px #10b981" : "none",
        }} />
      </div>
      {!isOnline && (
        <div style={{ color: "#4b5563", fontSize: "10px", marginTop: "4px" }}>
          Fase {agent.phase}
        </div>
      )}
    </div>
  );
}
