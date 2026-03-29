package router

import (
	"context"
	"encoding/json"
	"net/http"
	"time"

	"github.com/adelmo/agent-platform/gateway/internal/orchestrator"
	"github.com/adelmo/agent-platform/gateway/internal/ws"
	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"
)

func New(hub *ws.Hub) http.Handler {
	r := chi.NewRouter()

	r.Use(middleware.Logger)
	r.Use(middleware.Recoverer)
	r.Use(middleware.Timeout(5 * time.Minute))
	r.Use(corsMiddleware)

	orch := orchestrator.NewClient()

	// WebSocket endpoint
	r.Get("/ws", func(w http.ResponseWriter, r *http.Request) {
		ws.ServeWS(hub, w, r, makeMessageHandler(hub, orch))
	})

	// REST endpoints
	r.Get("/health", healthHandler(orch))
	r.Get("/agents/status", agentsStatusHandler(orch))
	r.Get("/agents/welcome", agentsWelcomeHandler())

	return r
}

// makeMessageHandler cria o handler de mensagens WebSocket.
func makeMessageHandler(hub *ws.Hub, orch *orchestrator.OrchestratorClient) ws.MessageHandler {
	return func(sessionID string, msg *ws.InboundMessage) {
		msgID := msg.MessageID
		if msgID == "" {
			msgID = uuid.New().String()
		}

		req := &orchestrator.Request{
			MessageID: msgID,
			SessionID: sessionID,
			Type:      msg.Type,
			Content:   msg.Content,
			Metadata:  msg.Metadata,
		}

		ctx := context.Background()

		err := orch.SendAndStream(ctx, req, func(event *orchestrator.StreamEvent) {
			payload, err := json.Marshal(map[string]interface{}{
				"message_id": msgID,
				"agent":      event.Agent,
				"type":       event.Type,
				"content":    event.Content,
				"metadata":   event.Metadata,
				"timestamp":  event.Timestamp,
			})
			if err != nil {
				return
			}
			hub.SendToSession(sessionID, payload)
		})

		if err != nil {
			errPayload, _ := json.Marshal(map[string]interface{}{
				"message_id": msgID,
				"agent":      "system",
				"type":       "error",
				"content":    "Falha ao processar mensagem: " + err.Error(),
				"timestamp":  time.Now().UTC().Format(time.RFC3339),
			})
			hub.SendToSession(sessionID, errPayload)
		}
	}
}

func healthHandler(orch *orchestrator.OrchestratorClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 3*time.Second)
		defer cancel()

		orchStatus := "ok"
		if err := orch.HealthCheck(ctx); err != nil {
			orchStatus = "degraded: " + err.Error()
		}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"status":       "ok",
			"gateway":      "ok",
			"orchestrator": orchStatus,
			"timestamp":    time.Now().UTC().Format(time.RFC3339),
		})
	}
}

func agentsStatusHandler(orch *orchestrator.OrchestratorClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// TODO: buscar status real dos agents via orchestrator
		agents := []map[string]string{
			{"name": "Beholder",  "status": "online",  "role": "observability"},
			{"name": "Metatron",  "status": "online",  "role": "documentation"},
			{"name": "LogicX",   "status": "offline", "role": "reasoning"},
			{"name": "Vops",     "status": "offline", "role": "infrastructure"},
			{"name": "CyberT",   "status": "offline", "role": "security"},
			{"name": "Zerocool", "status": "offline", "role": "pentesting"},
		}
		_ = orch
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]interface{}{
			"agents":    agents,
			"timestamp": time.Now().UTC().Format(time.RFC3339),
		})
	}
}

func agentsWelcomeHandler() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]string{
			"agent": "Beholder",
		})
	}
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}
