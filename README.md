# 📚 NER HistoricBooks IT

Pipeline end-to-end per l'analisi automatica di testi storici italiani digitalizzati tramite OCR.  
Il sistema pulisce gli errori di digitalizzazione, estrae entità storiche (personaggi, luoghi, date…), segmenta semanticamente il testo in capitoli e genera riassunti narrativi tramite AI.

> Progetto di tirocinio — Analisi NLP di testi letterari italiani antichi.

---

## Indice

- [Panoramica](#panoramica)
- [Architettura](#architettura)
- [La Pipeline](#la-pipeline)
  - [Fase 1 — Pulizia OCR](#fase-1--pulizia-ocr)
  - [Fase 2 — Estrazione Entità (NER)](#fase-2--estrazione-entità-ner)
  - [Fase 3 — Chunking Semantico e Capitoli](#fase-3--chunking-semantico-e-capitoli)
  - [Fase 4 — Riassunti AI](#fase-4--riassunti-ai)
- [Interfaccia Web](#interfaccia-web)
- [Struttura del Progetto](#struttura-del-progetto)
- [Prerequisiti](#prerequisiti)
- [Installazione e Avvio](#installazione-e-avvio)
  - [Avvio Locale (Sviluppo)](#avvio-locale-sviluppo)
  - [Avvio con Docker Compose (Produzione)](#avvio-con-docker-compose-produzione)
- [Configurazione](#configurazione)
- [API Reference](#api-reference)
- [Formato dei Dati](#formato-dei-dati)
- [Tecnologie](#tecnologie)

---

## Panoramica

Il progetto affronta un problema concreto: i testi storici italiani digitalizzati tramite OCR (Optical Character Recognition) contengono numerosi errori — lettere scambiate, capolettera staccati (`L udovico` invece di `Ludovico`), simboli estranei, punteggiatura corrotta. Questi errori rendono i testi inutilizzabili per qualsiasi analisi computazionale.

La pipeline risolve questo problema in 4 fasi automatiche:

```
                  ┌─────────────────────────────────────────────────────────────┐
                  │                    HistoricBook Pipeline                    │
                  └─────────────────────────────────────────────────────────────┘

  📄 Upload              🧹 Fase 1              🏷️ Fase 2             📐 Fase 3              📝 Fase 4
  Testo OCR    ───►    Pulizia OCR    ───►   Estrazione NER   ───►   Chunking +    ───►   Riassunti AI
  (grezzo)           (LLM + C Rules)        (BERT fine-tuned)        Capitoli            (Claude Haiku)
```

Il dataset incluso contiene **189 testi** della letteratura italiana — dall'Orlando Furioso alla Divina Commedia, dai Promessi Sposi al Decameron, passando per Leopardi, Machiavelli, Goldoni, Tasso, Vasari e molti altri.

---

## Architettura

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Docker Compose                                 │
│                                                                         │
│  ┌──────────────────┐   ┌──────────────────┐   ┌────────────────────┐  │
│  │    Frontend       │   │     Backend      │   │      Ollama        │  │
│  │   (Angular 21)    │   │    (FastAPI)      │   │   (qwen2.5:3b)    │  │
│  │                   │   │                   │   │                    │  │
│  │  Dashboard        │   │  REST API         │   │  LLM locale per   │  │
│  │  Analisi NER      │──►│  Pipeline Engine  │──►│  pulizia OCR      │  │
│  │  Lettore Capitoli │   │  SQLite DB        │   │                    │  │
│  │  Riassunti        │   │  File I/O         │   │                    │  │
│  │                   │   │                   │   │                    │  │
│  │  :80 (nginx)      │   │  :8000 (uvicorn)  │   │  :11434            │  │
│  └──────────────────┘   └────────┬──────────┘   └────────────────────┘  │
│                                  │                                       │
│                          ┌───────┴────────┐                              │
│                          │   SLM Locale    │                              │
│                          │(WIP: Riassunti) │                              │
│                          │                 │                              │
│                          └────────────────┘                              │
└─────────────────────────────────────────────────────────────────────────┘
```

| Componente | Ruolo |
|---|---|
| **Frontend** | SPA Angular con dashboard di gestione, viewer con evidenziazione entità, grafici NER e lettore di riassunti |
| **Backend** | API FastAPI che orchestra la pipeline, gestisce il database SQLite e serve i dati al frontend |
| **Ollama** | Server LLM locale che esegue il modello `qwen2.5:3b` per la correzione intelligente degli errori OCR |
| **SLM Locale (WIP)** | Modello locale per la generazione dei riassunti (attualmente in sviluppo) |

---

## La Pipeline

### Fase 1 — Pulizia OCR

La pulizia avviene in **due passaggi** complementari: un LLM per le correzioni contestuali e un programma C compilato per le regole deterministiche.

#### 1a. LLM Cleaner (Ollama)

Il testo viene diviso in chunk da ~1500 caratteri e inviato a `qwen2.5:3b` con un prompt specializzato in filologia italiana. Il modello restituisce un array JSON di correzioni:

```json
[
  {"errato": "disse il paladin o riandò verso", "corretto": "disse il paladino Orlando verso"},
  {"errato": "L udovico Ariosto", "corretto": "Ludovico Ariosto"}
]
```

Le correzioni vengono applicate tramite sostituzione nel testo originale. Parametri: `temperature: 0.1` (output deterministico), timeout 600s per chunk.

#### 1b. C Cleaner (Regole Deterministiche)

Un programma C compilato (~670 righe) applica 5 livelli di pulizia sequenziale:

1. **Rimozione simboli estranei** — `■ • ► ♦ _ ^ | < > \ * = ~ ± ✓ ¬`
2. **Regole generali OCR** — ~20 euristiche:
   - Fusione apostrofi isolati: `l '` → `l'`, `d '` → `d'`
   - Sostituzione cifre: `1'amore` → `l'amore`, `0rlando` → `Orlando`
   - Virgolette: `"parola"` → `«parola»`
   - Pulizia spazi multipli, trattini a fine riga
3. **Correzioni semantiche** — Riconnessione capolettera staccati (`M atteo` → `Matteo`, `A riosto` → `Ariosto`) + dizionario di correzioni note
4. **Pulizia terminazioni** — Rimozione consonanti terminali anomale (residui OCR)
5. **Filtro token spazzatura** — Rimozione token con <50% caratteri alfabetici o senza vocali

### Fase 2 — Estrazione Entità (NER)

Utilizza un modello **BERT fine-tuned** su testi storici italiani (`aendriu/bert-ner-italian-historical`, pubblicato su HuggingFace).

**9 categorie di entità**:

| Label | Tipo | Esempio |
|-------|------|---------|
| `PER` | Persona | *Ludovico Ariosto*, *Don Rodrigo* |
| `LOC` | Luogo | *Milano*, *Lago di Como* |
| `ORG` | Organizzazione | *Chiesa*, *Repubblica di Venezia* |
| `DATE` | Data | *1532*, *nel Quattrocento* |
| `WORK` | Opera | *Orlando Furioso*, *Decameron* |
| `EVENT` | Evento | *Battaglia di Lepanto* |
| `TIT` | Titolo | *Conte*, *Marchese* |
| `REL` | Relazione/Religione | *cristiano*, *papa* |
| `FANT` | Personaggio fantastico | *Angelica*, *Gradasso* |

**Processo**:
1. Il testo viene segmentato in chunk elaborabili dal modello tramite un algoritmo a cascata:
   - Individuazione automatica delle sezioni letterarie (Capitoli, Canti, ecc.) tramite RegEx.
   - Divisione in paragrafi all'interno delle sezioni.
   - Raggruppamento dei paragrafi in blocchi fino a un **massimo di 2000 caratteri** (per rispettare il limite dei 512 token di BERT ed evitare troncamenti). Se un singolo paragrafo supera il limite, viene ulteriormente diviso per frasi.
   - Sovrapposizione ("overlap") di **300 caratteri** tra chunk consecutivi per evitare che le entità vengano tagliate a metà sui bordi.
2. Ogni chunk viene processato dalla pipeline HuggingFace `token-classification`
3. Le entità vengono validate: score ≥ 0.65, minimo 3 caratteri, rapporto alfanumerico ≥ 0.6
4. Regole specifiche per tipo: `PER` richiede maiuscola, `FANT` richiede score ≥ 0.75, `DATE` validato con regex
5. Le entità duplicate tra chunk sovrapposti vengono deduplicate
6. Output: lista di entità con parola, tipo, score di confidenza e posizione nel testo (offset start/end)

### Fase 3 — Chunking Semantico e Capitoli

#### 3a. Chunking Semantico

Utilizza **SentenceTransformer** (`paraphrase-multilingual-MiniLM-L12-v2`) per segmentare il testo in base al contenuto semantico, non alla lunghezza arbitraria.

1. Il testo viene diviso in paragrafi
2. Ogni paragrafo viene convertito in un embedding vettoriale
3. Si calcola la similarità coseno tra paragrafi consecutivi
4. Dove la similarità scende sotto la soglia (0.5), si inserisce un confine di chunk
5. Vengono anche rilevati i confini espliciti nel testo (`CAPITOLO`, `CANTO`, `LIBRO`, `PARTE` + numerali romani/arabi)
6. Ogni chunk risultante contiene: testo, offset nel documento, suggerimento di argomento (`topic_hint`) e le entità NER presenti

#### 3b. Raggruppamento Capitoli

I chunk semantici vengono raggruppati sequenzialmente in macro-capitoli (ogni 8 chunk). Ogni capitolo viene salvato nel database con i suoi estremi di testo e i chunk corrispondenti vengono copiati in sottocartelle numerate.

### Fase 4 — Riassunti AI (Work in Progress)

> ⚠️ **Fase in riscrittura**: L'utilizzo di AWS Bedrock e Claude Haiku è stato rimosso per mantenere il progetto 100% locale ed esente da API key esterne. Questa fase è attualmente un placeholder testuale in attesa dell'integrazione di un SLM (Small Language Model) locale dedicato alla sintesi testuale.

---

## Interfaccia Web

L'interfaccia è una SPA Angular con due pagine principali.

### Dashboard

La pagina principale permette di:
- **Caricare** nuovi libri (formati `.json` con campo `contenuto`, oppure `.txt`)
- **Selezionare** un libro dalla lista
- **Avviare** la pipeline (completa o fase per fase con controllo dei prerequisiti)
- **Visualizzare** un'anteprima del testo pulito
- **Scaricare** tutti i dati elaborati come file ZIP strutturato
- **Monitorare** lo stato di avanzamento tramite modale con log in tempo reale

### Pagina di Analisi

Accessibile cliccando "Analizza libro", offre 4 sezioni navigabili:

#### 🔍 Pulizia OCR
Confronto visuale prima/dopo la pulizia con statistiche:
- Conteggio caratteri originali vs puliti
- Caratteri rimossi e percentuale di pulizia
- Testo originale e testo pulito affiancati

#### 🏷️ Entità (NER)
Panoramica completa delle entità estratte:
- **Grafico a ciambella** con distribuzione per tipo (PER, LOC, ORG…)
- **Top 15 entità** più citate
- **Filtri per tipo** con conteggio
- **Ricerca testuale** tra le entità
- **Lista chip** con badge colorati per tipo e conteggio occorrenze

#### 📖 Lettore con NER
Lettura del testo con entità evidenziate inline:
- Selezione capitolo dalla lista laterale con ricerca
- Testo del capitolo con **evidenziazione colorata** delle entità direttamente nel testo
- **Pannello accordion comprimibile** con lista di tutte le entità distinte del capitolo
- Legenda colori per tipo di entità

Colori entità: `PER` rosa, `LOC` blu, `ORG` giallo, `DATE` verde, `WORK` viola, `FANT` rosa, `TIT` teal, `REL` rosso, `EVENT` ambra.

#### 📝 Riassunti
Navigazione e lettura dei riassunti generati:
- Lista capitoli con indicatore ✅/○ (riassunto presente/assente)
- Testo del riassunto narrativo generato da Claude
- Navigazione Precedente/Successivo

---

## Struttura del Progetto

```
ner-historicbooks-it/
│
├── backend/                          # API Python + Pipeline AI
│   ├── app/
│   │   ├── config.py                 # Configurazione centralizzata (env vars)
│   │   ├── database.py               # Modelli ORM: Book, Chapter, Summary
│   │   ├── main.py                   # Entrypoint FastAPI
│   │   ├── services.py               # Orchestrazione pipeline (4 fasi)
│   │   ├── routers/
│   │   │   ├── books.py              # CRUD libri, upload, export ZIP
│   │   │   ├── pipeline.py           # Avvio fasi pipeline + progress
│   │   │   └── data.py               # Endpoint di lettura dati (testo, NER, chunk)
│   │   ├── ocr/
│   │   │   ├── llm_cleaner.py        # Pulizia OCR tramite Ollama (qwen2.5:3b)
│   │   │   └── c_cleaner/
│   │   │       ├── src/ocr_cleaner.c # Pulizia OCR rule-based in C (671 righe)
│   │   │       ├── src/cJSON.c       # Libreria JSON parser
│   │   │       └── Makefile
│   │   ├── ner/
│   │   │   ├── ner_extractor.py      # Pipeline NER con BERT fine-tuned
│   │   │   └── chunking.py           # Utilità di segmentazione testo
│   │   └── semantic/
│   │       ├── chunker.py            # Chunking basato su embeddings
│   │       ├── chapter_grouper.py    # Raggruppamento chunk in capitoli
│   │       └── summarizer.py         # Generazione riassunti (Claude Haiku)
│   ├── data/
│   │   └── raw/                      # 189 testi italiani digitalizzati
│   ├── Dockerfile                    # Multi-stage: compilazione C + runtime Python
│   ├── requirements.txt
│   └── .env.example
│
├── frontend/                         # SPA Angular 21
│   ├── src/app/
│   │   ├── components/
│   │   │   ├── dashboard/            # Dashboard: upload, pipeline, anteprima
│   │   │   └── analysis/             # Analisi: OCR, NER, Lettore, Riassunti
│   │   └── services/
│   │       ├── api.service.ts        # Client HTTP per tutte le API
│   │       └── book-state.service.ts # Stato globale con Angular Signals
│   ├── Dockerfile                    # Multi-stage: build Angular + Nginx
│   └── nginx.conf                    # Routing SPA + reverse proxy /api/
│
├── docker-compose.yml                # 3 servizi: backend + frontend + ollama
└── start.sh                          # Script avvio locale (sviluppo)
```

---

## Prerequisiti

| Strumento | Versione minima | Utilizzo |
|-----------|:-:|---|
| **Docker + Docker Compose** | — | ✅ Raccomandato: avvia tutto con un solo comando |
| **Python** | 3.10+ | Solo per sviluppo locale senza Docker |
| **Node.js** | 18+ | Solo per sviluppo locale senza Docker |
| **GCC + Make** | — | Solo per sviluppo locale senza Docker |
| **Ollama** | — | Solo per sviluppo locale (in Docker è incluso) |

> **🚀 Consiglio**: Usa **Docker Compose** (`docker compose up --build`) per evitare di installare manualmente Python, Node.js, GCC e Ollama. Un solo comando avvia tutto automaticamente.


---

## Installazione e Avvio

### Avvio Locale (Sviluppo)

#### 1. Clona il repository

```bash
git clone https://github.com/aendriu/ner-historicbooks-it.git
cd ner-historicbooks-it
```

#### 2. Compila il C Cleaner

```bash
cd backend/app/ocr/c_cleaner
make
cd ../../../..
```

Produce il binario `backend/app/ocr/c_cleaner/bin/ocr_cleaner`.

#### 3. Configura le variabili d'ambiente

```bash
cp backend/.env.example backend/.env
# Modifica backend/.env con il tuo editor
```

#### 4. Installa e avvia Ollama

```bash
# Installa Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Scarica il modello LLM
ollama pull qwen2.5:3b
```

#### 5. Installa le dipendenze

```bash
# Backend
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd ..

# Frontend
cd frontend
npm install
cd ..
```

#### 6. Avvia

Puoi avviare contemporaneamente backend e frontend con il comodo script:

```bash
bash start.sh
```

*(In alternativa, puoi avviare i servizi separatamente in due terminali: `uvicorn app.main:app` nel backend e `npm start` nel frontend).*

L'applicazione sarà disponibile su:

| Servizio | URL |
|---|---|
| Frontend | http://localhost:4200 |
| API Backend | http://localhost:8000 |
| Documentazione API (Swagger) | http://localhost:8000/docs |

---

### Avvio con Docker Compose (Produzione)

```bash
docker compose up --build
```

Al primo avvio, Ollama scaricherà automaticamente il modello `qwen2.5:3b` (~2 GB). Il backend attenderà che Ollama sia pronto (healthcheck) prima di partire.

| Servizio | URL |
|---|---|
| Frontend | http://localhost |
| API Backend | http://localhost:8000 |



---

## Configurazione

Tutte le impostazioni sono gestite tramite variabili d'ambiente nel file `backend/.env`:

```env
# ── Ollama (LLM per pulizia OCR) ─────────────────────────
OLLAMA_HOST=localhost              # IP/hostname del server Ollama
OLLAMA_PORT=11434
OLLAMA_MODEL=qwen2.5:3b           # Modello LLM da utilizzare

# ── NER ───────────────────────────────────────────────────
NER_MODEL_NAME=aendriu/bert-ner-italian-historical
NER_SCORE_THRESHOLD=0.65          # Soglia confidenza (0.0–1.0)
NER_MIN_ENTITY_CHARS=3            # Lunghezza minima entità

# ── Chunking Semantico ───────────────────────────────────
SEMANTIC_EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
SEMANTIC_SIMILARITY_THRESHOLD=0.5 # Soglia per confini di chunk

# ── Database ──────────────────────────────────────────────
DB_FILENAME=historicbooks.db
```

---

## API Reference

### Gestione Libri

| Metodo | Endpoint | Descrizione |
|:---:|---|---|
| `GET` | `/api/books` | Lista di tutti i libri con stato pipeline |
| `GET` | `/api/books/{id}` | Dettagli di un libro (incluse flag disponibilità dati) |
| `POST` | `/api/books/upload` | Upload file `.json` o `.txt` (multipart/form-data) |
| `GET` | `/api/books/{id}/export` | Download ZIP con tutti i dati elaborati |

### Esecuzione Pipeline

| Metodo | Endpoint | Descrizione |
|:---:|---|---|
| `POST` | `/api/books/{id}/run/all` | Avvia pipeline completa (4 fasi) |
| `POST` | `/api/books/{id}/run/clean` | Solo pulizia OCR (LLM + C cleaner) |
| `POST` | `/api/books/{id}/run/ner` | Solo estrazione NER |
| `POST` | `/api/books/{id}/run/chunking` | Solo chunking semantico |
| `POST` | `/api/books/{id}/run/chapters` | Solo raggruppamento capitoli |
| `POST` | `/api/books/{id}/run/summaries` | Solo generazione riassunti |
| `GET` | `/api/books/{id}/progress/{fase}` | Stato avanzamento fase (polling) |

### Lettura Dati

| Metodo | Endpoint | Descrizione |
|:---:|---|---|
| `GET` | `/api/books/{id}/text` | Testo grezzo + pulito (anteprima 50K char) |
| `GET` | `/api/books/{id}/ner` | Tutte le entità estratte con posizioni |
| `GET` | `/api/books/{id}/chunks` | Tutti i chunk semantici |
| `GET` | `/api/books/{id}/chapters/{cap}/chunks` | Chunk di un capitolo specifico |
| `GET` | `/api/books/{id}/chapters/{cap}/summary` | Riassunto di un capitolo |
| `GET` | `/api/books/{id}/summaries` | Tutti i riassunti dei capitoli |

Tutte le pipeline vengono eseguite in background. Lo stato si monitora con l'endpoint `progress`.

---

## Formato dei Dati

### Input

File JSON con il testo nel campo `contenuto`:

```json
{
  "contenuto": "CAPITOLO PRIMO\n\nQuel ramo del lago di Como..."
}
```

Vengono accettati anche i campi `text` o `content` (normalizzati automaticamente), e file `.txt` puri.

### Output (Esportazione ZIP)

```
I Promessi Sposi/
├── README.txt                              # Descrizione del contenuto
├── 00_originale/
│   ├── originale.json                      # File OCR originale
│   └── originale.txt                       # Solo testo estratto
├── 01_testo_pulito/
│   ├── testo_pulito.json                   # JSON con testo corretto
│   └── testo_pulito.txt                    # Solo testo pulito
├── 02_entita_ner/
│   ├── entita.json                         # Entità in formato JSON
│   └── entita.csv                          # Entità in formato CSV
├── 03_chunks_semantici/
│   ├── manifest.json                       # Indice di tutti i chunk
│   └── chunk_NNN.json                      # Singolo chunk semantico
├── 04_capitoli/
│   └── capitoli.json                       # Manifest dei capitoli
└── 05_riassunti/
    ├── capitolo_001_Capitolo_1.txt         # Riassunto per capitolo
    └── _tutti_i_riassunti.txt              # Tutti i riassunti concatenati
```

### Formato Entità NER

```json
{
  "book_name": "promessi_sposi",
  "total_entities": 3247,
  "entities": [
    {
      "word": "Don Rodrigo",
      "label": "PER",
      "score": 0.97,
      "start": 1523,
      "end": 1534
    }
  ]
}
```

### Formato Chunk Semantico

```json
{
  "book_name": "promessi_sposi",
  "chunk_id": 42,
  "total_chunks": 145,
  "text": "Quel ramo del lago di Como...",
  "char_start": 52340,
  "char_end": 54280,
  "topic_hint": "Descrizione del paesaggio lombardo",
  "entities": [
    {"word": "Como", "label": "LOC", "score": 0.95}
  ]
}
```

---

## Tecnologie

| Strato | Tecnologia | Utilizzo |
|---|---|---|
| **Backend API** | FastAPI + Uvicorn | Server REST asincrono |
| **Database** | SQLite + SQLAlchemy | Storage libri, capitoli, riassunti |
| **Pulizia OCR (AI)** | Ollama + Qwen 2.5 3B | Correzione contestuale errori OCR |
| **Pulizia OCR (regole)** | C nativo (gcc) | Euristiche deterministiche ad alte prestazioni |
| **NER** | BERT fine-tuned (`dbmdz/bert-base-italian-cased`) | Estrazione entità storiche italiane |
| **Embeddings** | SentenceTransformer (MiniLM-L12-v2) | Segmentazione semantica del testo |
| **Riassunti (WIP)** | SLM Locale (Placeholder) | Generazione riassunti narrativi (In sviluppo) |
| **Frontend** | Angular 21 (standalone, signals) | Interfaccia web SPA |
| **Grafici** | Chart.js 4.5 | Visualizzazione distribuzione entità |
| **Web Server** | Nginx | Serving SPA + reverse proxy API |
| **Container** | Docker Compose | Deploy con 3 servizi orchestrati |
| **ML Runtime** | PyTorch + HuggingFace Transformers | Inferenza modello NER |
