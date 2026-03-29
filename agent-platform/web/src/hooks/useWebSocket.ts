import { useCallback, useEffect, useRef, useState } from "react";
import { AgentEvent } from "../types";

type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";

interface UseWebSocketOptions {
  url: string;
  onEvent: (event: AgentEvent) => void;
  onSessionId: (id: string) => void;
}

export function useWebSocket({ url, onEvent, onSessionId }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const reconnectTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setStatus("connecting");
    const ws = new WebSocket(url);

    ws.onopen = () => {
      setStatus("connected");
      reconnectAttempts.current = 0;
      console.log("[WS] Conectado ao Gateway");
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        // Handshake inicial — recebe session_id
        if (data.type === "connected" && data.session_id) {
          onSessionId(data.session_id);
          return;
        }
        if (data.type === "pong") return;

        onEvent(data as AgentEvent);
      } catch (err) {
        console.error("[WS] Erro ao parsear mensagem:", err);
      }
    };

    ws.onclose = () => {
      setStatus("disconnected");
      wsRef.current = null;
      // Reconexão exponencial (max 30s)
      const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
      reconnectAttempts.current++;
      console.log(`[WS] Desconectado. Reconectando em ${delay}ms...`);
      reconnectTimeout.current = setTimeout(connect, delay);
    };

    ws.onerror = (err) => {
      console.error("[WS] Erro:", err);
      setStatus("error");
    };

    wsRef.current = ws;
  }, [url, onEvent, onSessionId]);

  const send = useCallback((payload: object) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    } else {
      console.warn("[WS] Tentativa de envio sem conexão ativa");
    }
  }, []);

  const disconnect = useCallback(() => {
    if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current);
    wsRef.current?.close();
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { status, send };
}
