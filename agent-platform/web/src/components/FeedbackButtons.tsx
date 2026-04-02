import React, { useState } from "react";

interface Props {
  messageId: string;
  sessionId: string;
  agent: string;
  currentFeedback?: "positive" | "negative";
  onFeedback: (messageId: string, rating: "positive" | "negative") => void;
}

export function FeedbackButtons({ messageId, sessionId: _sessionId, agent: _agent, currentFeedback, onFeedback }: Props) {
  const [sent, setSent] = useState(false);

  const handleClick = (rating: "positive" | "negative") => {
    if (sent || currentFeedback) return;
    setSent(true);
    onFeedback(messageId, rating);
  };

  const isPositive = currentFeedback === "positive";
  const isNegative = currentFeedback === "negative";
  const disabled = sent || !!currentFeedback;

  return (
    <div style={{ display: "flex", gap: "6px", marginTop: "6px", alignItems: "center" }}>
      <button
        onClick={() => handleClick("positive")}
        disabled={disabled}
        title="Resposta útil"
        style={{
          background: "none",
          border: `1px solid ${isPositive ? "#10b981" : "#374151"}`,
          borderRadius: "6px",
          padding: "2px 8px",
          cursor: disabled ? "default" : "pointer",
          color: isPositive ? "#10b981" : "#6b7280",
          fontSize: "13px",
          transition: "all 0.15s",
          opacity: disabled && !isPositive ? 0.4 : 1,
        }}
      >
        👍
      </button>
      <button
        onClick={() => handleClick("negative")}
        disabled={disabled}
        title="Resposta não útil"
        style={{
          background: "none",
          border: `1px solid ${isNegative ? "#ef4444" : "#374151"}`,
          borderRadius: "6px",
          padding: "2px 8px",
          cursor: disabled ? "default" : "pointer",
          color: isNegative ? "#ef4444" : "#6b7280",
          fontSize: "13px",
          transition: "all 0.15s",
          opacity: disabled && !isNegative ? 0.4 : 1,
        }}
      >
        👎
      </button>
      {(sent && !currentFeedback) && (
        <span style={{ color: "#4b5563", fontSize: "11px" }}>Enviando...</span>
      )}
    </div>
  );
}
