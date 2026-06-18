#!/bin/bash

# 1. Avvia il backend mettendolo in esecuzione in background (usando la & finale)
cd /home/aendriu/Para/Project/tirocinio/backend
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 &

# 2. Salva il PID (Process ID) del backend appena avviato
BACKEND_PID=$!

# 3. Imposta una "trappola" per killare automaticamente il backend 
# quando premi Ctrl+C per stoppare lo script
trap "kill $BACKEND_PID" EXIT

# 4. Avvia il frontend in primo piano
cd /home/aendriu/Para/Project/tirocinio/frontend/
npm start
