package ws

import (
	"encoding/json"
	"log"
	"net/http"
	"time"

	"github.com/google/uuid"
	"github.com/gorilla/websocket"
)

const (
	writeWait      = 10 * time.Second
	pongWait       = 60 * time.Second
	pingPeriod     = (pongWait * 9) / 10
	maxMessageSize = 16 * 1024 // 16KB
)

var upgrader = websocket.Upgrader{
	ReadBufferSize:  1024,
	WriteBufferSize: 1024,
	CheckOrigin: func(r *http.Request) bool {
		// TODO: validar origin em produção
		return true
	},
}

// InboundMessage é a mensagem enviada pelo browser.
type InboundMessage struct {
	Type      string          `json:"type"`       // "user_message" | "approval" | "ping"
	Content   string          `json:"content"`
	MessageID string          `json:"message_id"` // gerado pelo frontend
	Metadata  json.RawMessage `json:"metadata,omitempty"`
}

// Client representa uma conexão WebSocket ativa.
type Client struct {
	hub       *Hub
	conn      *websocket.Conn
	send      chan []byte
	sessionID string
	handler   MessageHandler
}

// MessageHandler é a função chamada quando uma mensagem chega do browser.
type MessageHandler func(sessionID string, msg *InboundMessage)

func NewClient(hub *Hub, conn *websocket.Conn, handler MessageHandler) *Client {
	return &Client{
		hub:       hub,
		conn:      conn,
		send:      make(chan []byte, 256),
		sessionID: uuid.New().String(),
		handler:   handler,
	}
}

// ServeWS faz o upgrade HTTP->WebSocket e inicia as goroutines de leitura/escrita.
func ServeWS(hub *Hub, w http.ResponseWriter, r *http.Request, handler MessageHandler) {
	conn, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		log.Printf("[WS] Falha no upgrade: %v", err)
		return
	}

	client := NewClient(hub, conn, handler)
	hub.Register(client)

	// Envia o session_id ao cliente para ele usar nas mensagens
	welcome, _ := json.Marshal(map[string]string{
		"type":       "connected",
		"session_id": client.sessionID,
	})
	client.send <- welcome

	go client.writePump()
	go client.readPump()
}

func (c *Client) readPump() {
	defer func() {
		c.hub.Unregister(c)
		c.conn.Close()
	}()

	c.conn.SetReadLimit(maxMessageSize)
	c.conn.SetReadDeadline(time.Now().Add(pongWait))
	c.conn.SetPongHandler(func(string) error {
		c.conn.SetReadDeadline(time.Now().Add(pongWait))
		return nil
	})

	for {
		_, rawMsg, err := c.conn.ReadMessage()
		if err != nil {
			if websocket.IsUnexpectedCloseError(err, websocket.CloseGoingAway, websocket.CloseAbnormalClosure) {
				log.Printf("[WS] Erro de leitura: %v", err)
			}
			break
		}

		var msg InboundMessage
		if err := json.Unmarshal(rawMsg, &msg); err != nil {
			log.Printf("[WS] JSON inválido: %v", err)
			continue
		}

		if msg.Type == "ping" {
			pong, _ := json.Marshal(map[string]string{"type": "pong"})
			c.send <- pong
			continue
		}

		if c.handler != nil {
			go c.handler(c.sessionID, &msg)
		}
	}
}

func (c *Client) writePump() {
	ticker := time.NewTicker(pingPeriod)
	defer func() {
		ticker.Stop()
		c.conn.Close()
	}()

	for {
		select {
		case message, ok := <-c.send:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if !ok {
				c.conn.WriteMessage(websocket.CloseMessage, []byte{})
				return
			}
			if err := c.conn.WriteMessage(websocket.TextMessage, message); err != nil {
				return
			}

		case <-ticker.C:
			c.conn.SetWriteDeadline(time.Now().Add(writeWait))
			if err := c.conn.WriteMessage(websocket.PingMessage, nil); err != nil {
				return
			}
		}
	}
}
