#!/usr/bin/env bash
# Reinicia UI y API para que pasta detecte wg0

podman rm -f ai-queue-ui ai-queue-api

podman run -d --name ai-queue-api \
  --network ai-queue \
  -p 0.0.0.0:8000:8000 \
  -e DATABASE_URL=postgresql://ai_queue:testpass@ai-queue-postgres/ai_queue \
  -e REDIS_URL=redis://:testpass@ai-queue-redis:6379 \
  -e API_KEY=testkey \
  localhost/ai-queue-api

podman run -d --name ai-queue-ui \
  --network ai-queue \
  -p 0.0.0.0:3000:3000 \
  localhost/ai-queue-ui

echo "Contenedores reiniciados"
podman ps --format "{{.Names}}\t{{.Ports}}\t{{.Status}}"
