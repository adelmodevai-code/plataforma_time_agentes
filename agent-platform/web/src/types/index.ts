export type AgentName =
  | "Metatron"
  | "Beholder"
  | "LogicX"
  | "Vops"
  | "CyberT"
  | "Zerocool"
  | "system";

export type EventType =
  | "typing"
  | "message"
  | "action"
  | "approval_request"
  | "file_created"
  | "complete"
  | "error"
  | "connected";

export interface FileAttachment {
  filename: string;
  download_url: string;
  size_bytes?: number;
}

export interface AgentEvent {
  message_id: string;
  agent: AgentName;
  type: EventType;
  content: string;
  metadata?: Record<string, unknown>;
  timestamp: string;
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  agent?: AgentName;
  content: string;
  timestamp: string;
  isStreaming?: boolean;
  files?: FileAttachment[];
}

export interface AgentStatus {
  name: AgentName;
  status: "online" | "offline" | "busy";
  role: string;
  phase: number;
}

export interface ApprovalRequest {
  request_id: string;
  vulnerability: string;
  target: string;
  test_type: string;
  risk_level: "low" | "medium" | "high";
  description: string;
}
