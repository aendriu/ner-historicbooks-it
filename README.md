# 📚 HistoricBook Pipeline

Un sistema completo di analisi e valorizzazione di testi storici italiani in lingua antica. Carica un libro OCR-izzato, il sistema lo pulisce automaticamente, estrae le entità storiche (personaggi, luoghi, date…), lo segmenta semanticamente in capitoli e genera riassunti narrativi tramite AI.

---

## Architettura

```
tirocinio/
├── backend/          # API Python/FastAPI + pipeline AI
│   ├── app/
│   │   ├── config.py         # Configurazione centralizzata (env vars)
│   │   ├── database.py       # Modelli SQLAlchemy (SQLite)
│   │   ├── services.py       # Orchestrazione pipeline completa
│   │   ├── ocr/              # Pulizia OCR (LLM Ollama + C cleaner)
│   │   │   └── c_cleaner/    # ⚠️ Sub-repo C — vedi sezione dedicata
│   │   ├── ner/              # Estrazione entità storiche (BERT fine-tuned)
│   │   ├── semantic/         # Chunking, raggruppamento capitoli, riassunti
│   │   └── routers/          # Endpoint FastAPI (books, pipeline, data)
│   ├── data/                 # Dati generati dalla pipeline (ignorato da git)
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/         # Angular SPA
│   ├── src/app/
│   │   ├── components/
│   │   │   ├── dashboard/    # Lista libri + avvio pipeline
│   │   │   └── analysis/     # Viewer OCR/NER/Capitoli/Riassunti
│   │   └── services/         # ApiService, BookStateService
│   └── Dockerfile
├── docker-compose.yml
└── start.sh          # Script avvio locale (senza Docker)
```

### Pipeline di elaborazione

```
Upload PDF/TXT  →  [OCR LLM Cleaner]  →  [C Cleaner]
                          ↓
              [NER Extraction (BERT)]
                          ↓
            [Semantic Chunking (MiniLM)]
                          ↓
             [Chapter Grouper (euristiche)]
                          ↓
          [Summarizer (Claude Haiku via AWS Bedrock)]
```

---

## Prerequisiti

| Strumento | Versione minima | Nota |
|-----------|----------------|------|
| Python | 3.10+ | Con `pip` |
| Node.js | 18+ | Con `npm` |
| GCC | qualsiasi | Per compilare il C cleaner |
| Make | qualsiasi | Per build C cleaner |
| Ollama | qualsiasi | Per la pulizia OCR |
| AWS CLI | qualsiasi | Per i riassunti via Claude Haiku |

---

## Avvio Locale (Sviluppo)

### 1. Clona il repository

```bash
git clone <url-repo>
cd tirocinio
```

### 2. Compila il C Cleaner (una tantum)

```bash
cd backend/app/ocr/c_cleaner
make
cd ../../../..
```

> Questo compila il binario `backend/app/ocr/c_cleaner/bin/ocr_cleaner` che viene usato dopo il passaggio LLM per una pulizia strutturale più veloce del JSON.

### 3. Configura le variabili d'ambiente

```bash
cp backend/.env.example backend/.env
```

Modifica `backend/.env`:

```env
# ── Ollama (LLM locale per pulizia OCR) ──
OLLAMA_HOST=localhost          # oppure l'IP del server remoto
OLLAMA_PORT=11434
OLLAMA_MODEL=qwen2.5:3b

# ── NER ──
NER_MODEL_NAME=aendriu/bert-ner-italian-historical
NER_SCORE_THRESHOLD=0.65      # soglia confidenza (0.0–1.0)

# ── Semantic ──
SEMANTIC_EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
SEMANTIC_SIMILARITY_THRESHOLD=0.5

# ── Database ──
DB_FILENAME=historicbooks.db
```

Per i riassunti (AWS Bedrock / Claude Haiku), assicurati che le credenziali AWS siano configurate:
```bash
aws configure   # oppure usa ~/.aws/credentials
```

### 4. Installa le dipendenze backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..
```

> ⚠️ `torch` e `transformers` richiedono qualche minuto per scaricarsi (~2 GB). Il modello NER viene scaricato automaticamente da HuggingFace Hub al primo utilizzo.

### 5. Installa Ollama e scarica il modello

```bash
# Installa Ollama (Linux)
curl -fsSL https://ollama.com/install.sh | sh

# Scarica il modello LLM
ollama pull qwen2.5:3b
```

### 6. Installa le dipendenze frontend

```bash
cd frontend
npm install
cd ..
```

### 7. Avvia tutto con lo script

```bash
# Prima modifica OLLAMA_HOST in start.sh se Ollama è su un server remoto
./start.sh
```

L'applicazione sarà disponibile su:
- **Frontend**: http://localhost:4200
- **API Backend**: http://localhost:8000
- **Docs API (Swagger)**: http://localhost:8000/docs

---

## Avvio con Docker Compose (Produzione)

```bash
# Build e avvio di tutti i servizi (backend + frontend + ollama)
docker compose up --build

# Alla prima esecuzione, Ollama scaricherà il modello automaticamente.
# L'operazione richiede qualche minuto.
```

L'applicazione sarà disponibile su:
- **Frontend**: http://localhost:80
- **API Backend**: http://localhost:8000

> ⚠️ I riassunti via Claude Haiku richiedono credenziali AWS anche in modalità Docker. Monta il volume `~/.aws` nel container backend o usa variabili d'ambiente `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY`.

---

## Utilizzo dell'applicazione

1. **Dashboard** → Clicca "Carica Libro" e carica un file `.txt` o `.json` con il campo `contenuto`
2. **Avvia Pipeline** → Usa i bottoni per eseguire ogni fase in ordine (Pulizia OCR → NER → Chunking → Capitoli → Riassunti)
3. **Analisi** → Clicca su un libro per aprire il viewer con 4 sezioni:
   - **🔍 Pulizia OCR**: confronto visuale prima/dopo con statistiche
   - **🏷️ Entità (NER)**: grafico, top entità, ricerca per tipo
   - **📖 Lettore con NER**: testo con entità evidenziate inline + lista comprimibile per capitolo
   - **📝 Riassunti**: lettura dei riassunti generati da Claude, navigabili capitolo per capitolo

---

## ⚠️ Il sub-repo `c_cleaner` (importante)

La cartella `backend/app/ocr/c_cleaner/` è un progetto C indipendente (**ocr-historicbook-cleaner**) che è stato incluso **copiando direttamente i file** invece di usare un git submodule. Questo causa un problema: git rileva quella cartella come un repository annidato "orfano" senza `.gitmodules`.

### Cosa fare

Hai due opzioni:

**Opzione A — Convertirlo in git submodule (consigliata se hai un repo GitHub separato per il C cleaner):**
```bash
# Rimuovi la cartella dalla storia git (mantieni i file locali)
git rm --cached backend/app/ocr/c_cleaner -r

# Aggiungi il submodule puntando al repository GitHub del C cleaner
git submodule add https://github.com/<tuo-utente>/ocr-historicbook-cleaner backend/app/ocr/c_cleaner

git commit -m "chore: convert c_cleaner to proper git submodule"
```

**Opzione B — Tenere i file inline (più semplice, perde il collegamento al repo originale):**
```bash
# Rimuovi il .git interno se esiste, poi aggiungi i file normalmente
rm -rf backend/app/ocr/c_cleaner/.git   # se presente
git add backend/app/ocr/c_cleaner/
git commit -m "chore: include c_cleaner sources directly"
```

L'Opzione A è preferibile se il C cleaner è un tool riutilizzabile in altri progetti. L'Opzione B va bene se è pensato esclusivamente per questo progetto.

---

## Struttura dati generata

```
backend/data/
├── raw/          # File originali caricati
├── cleaned/      # Testo dopo pulizia OCR (JSON con campo "contenuto")
├── ner/          # Entità estratte per libro (*_entities.json)
├── semantic/     # Chunk semantici per libro (manifest.json + chunk_NNN.json)
└── chapters/     # Chunk raggruppati per capitolo (per_book/per_chapter/)
```

---

## Tecnologie

| Strato | Tecnologia |
|--------|-----------|
| API | FastAPI + Uvicorn |
| DB | SQLite via SQLAlchemy ORM |
| OCR LLM | Ollama (qwen2.5:3b) |
| OCR strutturale | C nativo (custom parser JSON) |
| NER | BERT fine-tuned (`aendriu/bert-ner-italian-historical`) |
| Embedding | `paraphrase-multilingual-MiniLM-L12-v2` |
| Riassunti | Claude Haiku via AWS Bedrock |
| Frontend | Angular 17+ (standalone components, signals) |
| Containerizzazione | Docker + Docker Compose |
