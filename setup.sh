#!/usr/bin/env bash
set -euo pipefail

PYTHON_VERSION=3.13.2
APP_DIR=/opt/qwen-api
APP_USER=qwen
MODEL=qwen3.5:4b

if [ "$(id -u)" -ne 0 ]; then
    echo "Run as root or with sudo." >&2
    exit 1
fi

apt-get update -y
apt-get install -y \
    build-essential \
    curl \
    wget \
    libssl-dev \
    libffi-dev \
    zlib1g-dev \
    libbz2-dev \
    libreadline-dev \
    libsqlite3-dev \
    libncursesw5-dev \
    xz-utils \
    liblzma-dev \
    uuid-dev \
    tk-dev

if ! command -v python3.13 &>/dev/null; then
    BUILD_DIR="$(mktemp -d)"
    cd "$BUILD_DIR"
    wget -q "https://www.python.org/ftp/python/${PYTHON_VERSION}/Python-${PYTHON_VERSION}.tgz"
    tar -xf "Python-${PYTHON_VERSION}.tgz"
    cd "Python-${PYTHON_VERSION}"
    ./configure --prefix=/usr/local
    make -j"$(nproc)"
    make altinstall
    cd /
    rm -rf "$BUILD_DIR"
fi

if ! command -v ollama &>/dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi

systemctl enable ollama
systemctl start ollama

mkdir -p /mnt/storage/ollama-models
chown ollama:ollama /mnt/storage/ollama-models
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<EOF
[Service]
Environment="OLLAMA_MODELS=/mnt/storage/ollama-models"
EOF
systemctl daemon-reload
systemctl restart ollama

for i in $(seq 1 15); do
    if curl -sf http://127.0.0.1:11434/api/tags &>/dev/null; then
        break
    fi
    sleep 2
done

if ! id "$APP_USER" &>/dev/null; then
    useradd --system --shell /usr/sbin/nologin --home-dir "$APP_DIR" --create-home "$APP_USER"
fi

mkdir -p "$APP_DIR"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/main.py" "$APP_DIR/"
cp "$SCRIPT_DIR/config.py" "$APP_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$APP_DIR/"

if [ ! -f "$APP_DIR/.env" ]; then
    cp "$SCRIPT_DIR/.env.example" "$APP_DIR/.env"
fi

if [ ! -d "$APP_DIR/venv" ]; then
    /usr/local/bin/python3.13 -m venv "$APP_DIR/venv"
fi

"$APP_DIR/venv/bin/pip" install --upgrade pip --quiet
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" --quiet

chown -R "$APP_USER:$APP_USER" "$APP_DIR"

cp "$SCRIPT_DIR/qwen-api.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable qwen-api

ollama pull "$MODEL"

systemctl start qwen-api

echo ""
echo "Setup complete."
echo "Edit $APP_DIR/.env to set your API key, then run: systemctl restart qwen-api"
echo "Health check: curl http://127.0.0.1:8000/health"