package router

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
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

	// Proxy de arquivos do Metatron
	r.Get("/files/*", filesProxyHandler(orch))

	// REST endpoints
	r.Post("/api/feedback", feedbackHandler(orch))
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

func feedbackHandler(orch *orchestrator.OrchestratorClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		body, err := io.ReadAll(r.Body)
		if err != nil {
			http.Error(w, "erro ao ler body", http.StatusBadRequest)
			return
		}

		resp, err := orch.SendFeedback(r.Context(), body)
		if err != nil {
			http.Error(w, "orchestrator indisponível: "+err.Error(), http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()

		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body) //nolint:errcheck
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

func filesProxyHandler(orch *orchestrator.OrchestratorClient) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Extrai tudo após /files/
		filePath := chi.URLParam(r, "*")
		target := fmt.Sprintf("%s/files/%s", orch.BaseURL(), filePath)

		ctx, cancel := context.WithTimeout(r.Context(), 30*time.Second)
		defer cancel()

		req, err := http.NewRequestWithContext(ctx, http.MethodGet, target, nil)
		if err != nil {
			http.Error(w, "erro ao criar requisição", http.StatusInternalServerError)
			return
		}

		resp, err := http.DefaultClient.Do(req)
		if err != nil {
			http.Error(w, "arquivo não disponível", http.StatusBadGateway)
			return
		}
		defer resp.Body.Close()

		// Copia headers relevantes
		for _, h := range []string{"Content-Type", "Content-Disposition", "Content-Length"} {
			if v := resp.Header.Get(h); v != "" {
				w.Header().Set(h, v)
			}
		}
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body) //nolint:errcheck
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
