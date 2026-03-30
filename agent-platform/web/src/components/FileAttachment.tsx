import React from "react";
import { FileAttachment as FileAttachmentType } from "../types";

const API_URL = (import.meta as ImportMeta & { env: Record<string, string> }).env?.VITE_API_URL ?? "http://localhost:8080";

const EXT_ICONS: Record<string, string> = {
  ".md":   "📄",
  ".txt":  "📝",
  ".json": "📋",
};

function extOf(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot).toLowerCase() : "";
}

function formatBytes(bytes?: number): string {
  if (!bytes) return "";
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
}

interface Props {
  file: FileAttachmentType;
}

export function FileAttachment({ file }: Props) {
  const ext = extOf(file.filename);
  const icon = EXT_ICONS[ext] ?? "📎";
  const href = `${API_URL}${file.download_url}`;

  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "8px",
        padding: "8px 14px",
        background: "#1f2937",
        border: "1px solid #7c3aed44",
        borderRadius: "8px",
        textDecoration: "none",
        color: "#c4b5fd",
        fontSize: "13px",
        fontWeight: 500,
        transition: "border-color 0.2s, background 0.2s",
        maxWidth: "340px",
      }}
      onMouseEnter={(e) => {
        (e.currentTarget as HTMLAnchorElement).style.borderColor = "#7c3aed";
        (e.currentTarget as HTMLAnchorElement).style.background = "#7c3aed22";
      }}
      onMouseLeave={(e) => {
        (e.currentTarget as HTMLAnchorElement).style.borderColor = "#7c3aed44";
        (e.currentTarget as HTMLAnchorElement).style.background = "#1f2937";
      }}
    >
      <span style={{ fontSize: "18px" }}>{icon}</span>
      <span style={{
        overflow: "hidden",
        textOverflow: "ellipsis",
        whiteSpace: "nowrap",
        flex: 1,
      }}>
        {file.filename}
      </span>
      {file.size_bytes != null && (
        <span style={{ color: "#6b7280", fontSize: "11px", flexShrink: 0 }}>
          {formatBytes(file.size_bytes)}
        </span>
      )}
      <span style={{ color: "#6b7280", fontSize: "11px", flexShrink: 0 }}>↗</span>
    </a>
  );
}
