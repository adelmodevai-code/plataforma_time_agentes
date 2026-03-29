package main

import (
	"log"
	"net/http"
	"os"

	"github.com/adelmo/agent-platform/gateway/internal/router"
	"github.com/adelmo/agent-platform/gateway/internal/ws"
)

func main() {
	hub := ws.NewHub()
	go hub.Run()

	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	r := router.New(hub)

	log.Printf("🚀 Agent Platform Gateway iniciando na porta %s", port)
	log.Printf("📡 WebSocket disponível em ws://localhost:%s/ws", port)
	log.Printf("💊 Health check em http://localhost:%s/health", port)

	if err := http.ListenAndServe(":"+port, r); err != nil {
		log.Fatalf("Erro ao iniciar servidor: %v", err)
	}
}
