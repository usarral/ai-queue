# ai-queue

Sistema de colas de tareas para un AI server que puede estar apagado.

## Arquitectura

```
Browser → Caddy → API (FastAPI) → PostgreSQL + Redis Streams
                               → WoL service (despierta el AI server si hay tareas)

AI Server (se enciende solo) → worker.py (systemd) → long-poll a la API → ejecuta tareas
```

## Instalación — Servidor siempre encendido

```bash
cp .env.example .env
# Edita .env con tus contraseñas, MAC e IP del AI server y dominio
nano .env

# Edita Caddyfile con tu dominio
nano Caddyfile

docker compose up -d
```

### Sin dominio (solo red local)

Cambia el `Caddyfile` a:
```
:80 {
    handle /api/* { reverse_proxy api:8000 }
    handle /healthz { reverse_proxy api:8000 }
    handle { reverse_proxy ui:3000 }
}
```

## Instalación — AI Server

Requisitos previos en el AI server:
- Python 3.11+
- Ollama corriendo en `localhost:11434` (para tareas `ollama_prompt`)
- `faster-whisper` instalado (para `whisper_transcription`): `pip install faster-whisper`
- **Wake-on-LAN habilitado en la BIOS**

```bash
# Copiar la carpeta worker/ al AI server y ejecutar como root:
sudo bash worker/install.sh

# Editar las variables de entorno:
sudo nano /etc/ai-queue-worker/env

# Iniciar el servicio:
sudo systemctl start ai-queue-worker
sudo systemctl status ai-queue-worker
```

`/etc/ai-queue-worker/env`:
```
API_URL=https://ai-queue.example.com
API_KEY=tu_api_key_aqui
WORKER_ID=ai-server-01
```

## Tipos de tarea

### `ollama_prompt`
```json
{
  "type": "ollama_prompt",
  "input_payload": {
    "model": "llama3.2",
    "prompt": "Explica qué es Redis en 2 frases."
  }
}
```

### `shell_command`
```json
{
  "type": "shell_command",
  "input_payload": {
    "command": "python3 /data/train.py --epochs 10",
    "timeout": 7200
  }
}
```

### `whisper_transcription`
```json
{
  "type": "whisper_transcription",
  "input_payload": {
    "file_path": "/data/audio.mp3",
    "language": "es",
    "model": "medium"
  }
}
```

## API rápida (curl)

```bash
API=https://ai-queue.example.com
KEY=tu_api_key

# Crear tarea
curl -X POST $API/api/tasks \
  -H "X-API-Key: $KEY" \
  -H "Content-Type: application/json" \
  -d '{"type":"ollama_prompt","input_payload":{"model":"llama3.2","prompt":"Hola"}}'

# Listar tareas pendientes
curl "$API/api/tasks?status=pending" -H "X-API-Key: $KEY"

# Stats
curl $API/api/stats -H "X-API-Key: $KEY"

# Forzar WoL manual
curl -X POST $API/api/system/wakeup -H "X-API-Key: $KEY"
```

## Wake-on-LAN

El servicio `wol` comprueba cada 2 minutos si hay tareas `pending`.
Si las hay y el AI server no responde a ping, envía un magic packet a la MAC configurada en `.env`.

Para que funcione:
1. Habilitar WoL en la BIOS del AI server
2. Configurar `AI_SERVER_MAC` y `AI_SERVER_IP` en `.env`
3. El servidor siempre-on debe estar en la **misma red local** que el AI server (para los magic packets)

## Variables de entorno

| Variable | Descripción | Ejemplo |
|---|---|---|
| `POSTGRES_PASSWORD` | Contraseña PostgreSQL | `s3cr3t` |
| `REDIS_PASSWORD` | Contraseña Redis | `s3cr3t` |
| `API_KEY` | Clave de autenticación de la API | `mi-clave-secreta` |
| `AI_SERVER_MAC` | MAC del AI server para WoL | `AA:BB:CC:DD:EE:FF` |
| `AI_SERVER_IP` | IP local del AI server | `192.168.1.100` |
| `BROADCAST_IP` | IP de broadcast de la red | `192.168.1.255` |
