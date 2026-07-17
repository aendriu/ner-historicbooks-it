#!/bin/bash
# ─────────────────────────────────────────────────────
# setup.sh — Configurazione iniziale del progetto
# Esegui una sola volta su un nuovo PC:   bash setup.sh
# ─────────────────────────────────────────────────────
set -e

echo "══════════════════════════════════════════════"
echo "  NER HistoricBooks IT — Setup iniziale"
echo "══════════════════════════════════════════════"

# ── 1. Fix DNS Docker (risolve "NewConnectionError" durante il build) ──
DAEMON_JSON="/etc/docker/daemon.json"

if [ -f "$DAEMON_JSON" ] && grep -q "dns" "$DAEMON_JSON" 2>/dev/null; then
    echo "[✓] Docker DNS già configurato."
else
    echo "[*] Configurazione DNS Docker (8.8.8.8)..."
    if [ -f "$DAEMON_JSON" ]; then
        # Aggiungi dns al file esistente (backup prima)
        sudo cp "$DAEMON_JSON" "${DAEMON_JSON}.bak"
        sudo python3 -c "
import json
with open('$DAEMON_JSON') as f:
    d = json.load(f)
d['dns'] = ['8.8.8.8', '8.8.4.4']
with open('$DAEMON_JSON', 'w') as f:
    json.dump(d, f, indent=2)
"
    else
        sudo mkdir -p /etc/docker
        echo '{"dns": ["8.8.8.8", "8.8.4.4"]}' | sudo tee "$DAEMON_JSON" > /dev/null
    fi
    echo "[*] Riavvio Docker..."
    sudo systemctl restart docker
    echo "[✓] Docker DNS configurato."
fi

# ── 2. Verifica .env ──
if [ ! -f ".env" ]; then
    echo ""
    echo "[!] File .env non trovato."
    echo "    Copia .env.example e configuralo:"
    echo "    cp .env.example .env"
    echo ""
else
    echo "[✓] File .env presente."
fi

# ── 3. Build Docker ──
echo ""
echo "[*] Build Docker in corso..."
docker compose build

echo ""
echo "══════════════════════════════════════════════"
echo "  [✓] Setup completato!"
echo ""
echo "  Per avviare:  docker compose up -d"
echo "  Frontend:     http://localhost"
echo "  Backend API:  http://localhost:8000"
echo "══════════════════════════════════════════════"
