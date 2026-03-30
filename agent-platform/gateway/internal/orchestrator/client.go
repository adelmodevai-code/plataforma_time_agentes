package orchestrator

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"time"
)

// OrchestratorClient faz chamadas HTTP ao Python Orchestrator.
type OrchestratorClient struct {
	baseURL    string
	httpClient *http.Client
}

// Request é o payload enviado ao Orchestrator.
type Request struct {
	MessageID string          `json:"message_id"`
	SessionID string          `json:"session_id"`
	Type      string          `json:"type"`        // "user_message" | "approval" | "denial"
	Content   string          `json:"content"`
	Metadata  json.RawMessage `json:"metadata,omitempty"`
}

// StreamEvent é um evento de streaming retornado pelo Orchestrator (SSE).
type StreamEvent struct {
	Agent     string          `json:"agent"`
	Type      string          `json:"type"`        // "typing" | "message" | "action" | "approval_request" | "complete" | "error"
	Content   string          `json:"content"`
	Metadata  json.RawMessage `json:"metadata,omitempty"`
	Timestamp string          `json:"timestamp"`
}

func NewClient() *OrchestratorClient {
	baseURL := os.Getenv("ORCHESTRATOR_URL")
	if baseURL == "" {
		baseURL = "http://localhost:8001"
	}
	return &OrchestratorClient{
		baseURL: baseURL,
		httpClient: &http.Client{
			Timeout: 5 * time.Minute, // agentes podem demorar
		},
	}
}

// SendAndStream envia uma mensagem ao Orchestrator e processa o stream SSE,
// chamando onEvent para cada evento recebido.
func (c *OrchestratorClient) SendAndStream(
	ctx context.Context,
	req *Request,
	onEvent func(*StreamEvent),
) error {
	body, err := json.Marshal(req)
	if err != nil {
		return fmt.Errorf("marshal request: %w", err)
	}

	httpReq, err := http.NewRequestWithContext(ctx, "POST",
		c.baseURL+"/v1/chat/stream", bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("criar request: %w", err)
	}
	httpReq.Header.Set("Content-Type", "application/json")
	httpReq.Header.Set("Accept", "text/event-stream")

	resp, err := c.httpClient.Do(httpReq)
	if err != nil {
		return fmt.Errorf("chamar orchestrator: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		b, _ := io.ReadAll(resp.Body)
		return fmt.Errorf("orchestrator retornou %d: %s", resp.StatusCode, string(b))
	}

	// Processa SSE line by line
	decoder := json.NewDecoder(resp.Body)
	buf := make([]byte, 0, 4096)
	lineBuf := bytes.NewBuffer(buf)

	rawBytes := make([]byte, 1)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		n, err := resp.Body.Read(rawBytes)
		if n > 0 {
			if rawBytes[0] == '\n' {
				line := lineBuf.String()
				lineBuf.Reset()
				if len(line) > 6 && line[:6] == "data: " {
					data := line[6:]
					if data == "[DONE]" {
						return nil
					}
					var event StreamEvent
					if err := json.Unmarshal([]byte(data), &event); err != nil {
						log.Printf("[Orchestrator] Evento inválido: %v | data: %s", err, data)
						continue
					}
					onEvent(&event)
				}
			} else {
				lineBuf.WriteByte(rawBytes[0])
			}
		}
		if err != nil {
			if err == io.EOF {
				return nil
			}
			_ = decoder // evitar unused import
			return fmt.Errorf("leitura SSE: %w", err)
		}
	}
}

// BaseURL retorna a URL base do orchestrator.
func (c *OrchestratorClient) BaseURL() string {
	return c.baseURL
}

// HealthCheck verifica se o Orchestrator está online.
func (c *OrchestratorClient) HealthCheck(ctx context.Context) error {
	req, _ := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/health", nil)
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("orchestrator unhealthy: %d", resp.StatusCode)
	}
	return nil
}
