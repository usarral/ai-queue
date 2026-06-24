#!/usr/bin/env bash
# Instala el worker en el AI server como servicio systemd.
# Ejecutar como root.

set -euo pipefail

INSTALL_DIR=/opt/ai-queue-worker
ENV_FILE=/etc/ai-queue-worker/env
SERVICE_FILE=/etc/systemd/system/ai-queue-worker.service

echo "=== AI Queue Worker installer ==="

# Crear usuario sin shell ni home
if ! id ai-worker &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin ai-worker
    echo "Created user ai-worker"
fi

# Copiar archivos
mkdir -p "$INSTALL_DIR"
cp -r "$(dirname "$0")"/* "$INSTALL_DIR/"
chown -R ai-worker:ai-worker "$INSTALL_DIR"

# Crear virtualenv e instalar dependencias
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# Crear archivo de entorno si no existe
if [ ! -f "$ENV_FILE" ]; then
    mkdir -p "$(dirname "$ENV_FILE")"
    cat > "$ENV_FILE" <<'EOF'
API_URL=https://ai-queue.example.com
API_KEY=changeme_api_key
WORKER_ID=ai-server-01
POLL_BLOCK=30
EOF
    chmod 600 "$ENV_FILE"
    echo ""
    echo "IMPORTANTE: edita $ENV_FILE con la URL y API key correctas antes de iniciar el servicio."
fi

# Instalar y activar el servicio
cp "$INSTALL_DIR/ai-queue-worker.service" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable ai-queue-worker

echo ""
echo "Instalación completada."
echo "  Edita $ENV_FILE y luego ejecuta: systemctl start ai-queue-worker"
echo "  Estado: systemctl status ai-queue-worker"
echo "  Logs:   journalctl -u ai-queue-worker -f"
