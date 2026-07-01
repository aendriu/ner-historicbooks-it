#!/bin/bash

echo "======================================"
echo "🚀 Avvio HistoricBook Pipeline..."
echo "======================================"

echo "[1/4] Pulizia di vecchi processi in esecuzione..."
pkill -f uvicorn || true
pkill -f "ng serve" || true
sleep 1

# Carica configurazione
ENV_FILE=".env"
if [ ! -f "$ENV_FILE" ]; then
    echo "📄 File .env non trovato. Creo una copia di default da .env.example..."
    cp .env.example .env
fi
OLLAMA_HOST_VAL="localhost"
OLLAMA_MODEL="qwen2.5:3b"

if [ -f "$ENV_FILE" ]; then
    HOST_FROM_ENV=$(grep "^OLLAMA_HOST=" "$ENV_FILE" | cut -d '=' -f2)
    MODEL_FROM_ENV=$(grep "^OLLAMA_MODEL=" "$ENV_FILE" | cut -d '=' -f2)
    [ -n "$MODEL_FROM_ENV" ] && OLLAMA_MODEL=$MODEL_FROM_ENV

    # Ignora valori placeholder (non URL e non hostname valido)
    if [ -n "$HOST_FROM_ENV" ] && echo "$HOST_FROM_ENV" | grep -qE "^(https?://|localhost|127\.0\.0\.1|[0-9]{1,3}\.[0-9]{1,3})"; then
        OLLAMA_HOST_VAL=$HOST_FROM_ENV
    else
        echo "⚠️  OLLAMA_HOST nel .env non è un indirizzo valido. Uso il PC locale (localhost)."
    fi
fi

# Formatta l'URL per le chiamate API
if [[ "$OLLAMA_HOST_VAL" == "http"* ]]; then
    OLLAMA_URL="$OLLAMA_HOST_VAL"
else
    OLLAMA_URL="http://${OLLAMA_HOST_VAL}:11434"
fi

echo ""
echo "[2/4] Verifica configurazione Ollama (LLM Cleaner)..."
if [[ "$OLLAMA_HOST_VAL" == *"localhost"* || "$OLLAMA_HOST_VAL" == *"127.0.0.1"* ]]; then
    echo "🤖 Uso la potenza del PC locale ($OLLAMA_URL)"
else
    echo "☁️ Uso il server remoto ($OLLAMA_URL)"
fi

# Controllo se Ollama risponde e check dei pesi
if curl --connect-timeout 5 -s -f "$OLLAMA_URL/api/tags" > /dev/null; then
    echo "✅ Connessione a Ollama riuscita!"
    
    # Cerca il nome del modello nel JSON restituito
    if curl -s "$OLLAMA_URL/api/tags" | grep -q "\"$OLLAMA_MODEL\""; then
        echo "✅ Modello '$OLLAMA_MODEL' trovato nei pesi. Pronto a partire!"
    else
        echo "⏳ ATTENZIONE: Il modello '$OLLAMA_MODEL' non è ancora presente."
        echo "   Inizio il download automatico dei pesi (~2GB)..."
        echo "   (Questo processo richiederà alcuni minuti a seconda della connessione)"
        
        # API di pull di Ollama (chiama e aspetta la fine)
        curl -s -X POST "$OLLAMA_URL/api/pull" -d "{\"name\": \"$OLLAMA_MODEL\"}" > /dev/null
        echo "✅ Download dei pesi completato con successo!"
    fi
else
    echo "❌ ATTENZIONE: Ollama non è raggiungibile all'indirizzo $OLLAMA_URL"
    echo "   Se stai usando il tuo PC locale, ricordati di avviare prima l'app Ollama."
    echo "   Se usi Colab, assicurati di aver messo il link giusto in backend/.env"
    echo "   L'applicazione si avvierà lo stesso, ma la pulizia OCR in pipeline fallirà."
fi

echo ""
echo "[3/4] Installazione dipendenze (se necessarie)..."

# Controllo C Cleaner
if [ ! -f "backend/app/ocr/c_cleaner/bin/ocr_cleaner" ]; then
    echo "⚙️ Compilazione C Cleaner..."
    cd backend/app/ocr/c_cleaner
    make > /dev/null
    cd ../../../../
fi

# Controllo Backend (.venv)
cd backend
if [ ! -d ".venv" ]; then
    echo "🐍 Creazione ambiente virtuale Python e installazione librerie..."
    python3 -m venv .venv
    ./.venv/bin/pip install -r requirements.txt > /dev/null
fi
cd ..

# Controllo Frontend (node_modules)
cd frontend
if [ ! -d "node_modules" ]; then
    echo "📦 Installazione dipendenze Node.js (potrebbe richiedere qualche minuto)..."
    npm install > /dev/null
fi
cd ..

echo ""
echo "[4/4] Avvio Applicazione..."
cd backend
./.venv/bin/python3 -m uvicorn app.main:app --env-file ../.env --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Trappola per killare il backend quando premi Ctrl+C
trap "kill $BACKEND_PID" EXIT

cd ../frontend/
npm start
