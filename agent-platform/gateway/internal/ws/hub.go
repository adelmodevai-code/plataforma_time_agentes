package ws

import (
	"log"
	"sync"
)

// Hub mantém o conjunto de clientes ativos e faz broadcast de mensagens.
type Hub struct {
	// Clientes registrados: session_id -> Client
	clients map[string]*Client

	// Canal para registrar novos clientes
	register chan *Client

	// Canal para desregistrar clientes
	unregister chan *Client

	// Canal de mensagens do Orchestrator para um cliente específico
	send chan *OutboundMessage

	mu sync.RWMutex
}

// OutboundMessage é uma mensagem direcionada a um session específico.
type OutboundMessage struct {
	SessionID string
	Payload   []byte
}

func NewHub() *Hub {
	return &Hub{
		clients:    make(map[string]*Client),
		register:   make(chan *Client, 64),
		unregister: make(chan *Client, 64),
		send:       make(chan *OutboundMessage, 256),
	}
}

func (h *Hub) Run() {
	for {
		select {
		case client := <-h.register:
			h.mu.Lock()
			h.clients[client.sessionID] = client
			h.mu.Unlock()
			log.Printf("[Hub] Cliente conectado: session=%s", client.sessionID)

		case client := <-h.unregister:
			h.mu.Lock()
			if _, ok := h.clients[client.sessionID]; ok {
				delete(h.clients, client.sessionID)
				close(client.send)
				log.Printf("[Hub] Cliente desconectado: session=%s", client.sessionID)
			}
			h.mu.Unlock()

		case msg := <-h.send:
			h.mu.RLock()
			client, ok := h.clients[msg.SessionID]
			h.mu.RUnlock()
			if ok {
				select {
				case client.send <- msg.Payload:
				default:
					// Buffer cheio — fecha a conexão
					h.mu.Lock()
					delete(h.clients, client.sessionID)
					close(client.send)
					h.mu.Unlock()
					log.Printf("[Hub] Buffer cheio, encerrando sessão: %s", client.sessionID)
				}
			}
		}
	}
}

// SendToSession envia uma mensagem para um session específico.
func (h *Hub) SendToSession(sessionID string, payload []byte) {
	h.send <- &OutboundMessage{SessionID: sessionID, Payload: payload}
}

// Register registra um novo cliente no hub.
func (h *Hub) Register(c *Client) {
	h.register <- c
}

// Unregister desregistra um cliente do hub.
func (h *Hub) Unregister(c *Client) {
	h.unregister <- c
}
