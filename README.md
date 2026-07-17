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
  - [Fase 4 — Riassunti AI (Sinossi Globale)](#fase-4--riassunti-ai-sinossi-globale)
- [Valutazione della Pipeline](#valutazione-della-pipeline)
  - [Valutazione NER (Fase 2)](#valutazione-ner-fase-2)
  - [Valutazione Chunking (Fase 3)](#valutazione-chunking-fase-3)
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

Pipeline automatica in 4 fasi per testi storici italiani digitalizzati tramite OCR:

1. **Pulizia OCR** — correzione errori di digitalizzazione (LLM + regole C)
2. **NER** — estrazione di entità (personaggi, luoghi, date, ecc.) con BERT fine-tuned
3. **Chunking semantico** — segmentazione del testo in capitoli tramite embedding vettoriali
4. **Riassunti AI** — generazione di riassunti gerarchici (per capitolo + sinossi globale)

```
                  ┌─────────────────────────────────────────────────────────────┐
                  │                    HistoricBook Pipeline                    │
                  └─────────────────────────────────────────────────────────────┘

  📄 Upload              🧹 Fase 1              🏷️ Fase 2             📐 Fase 3              📝 Fase 4
  Testo OCR    ───►    Pulizia OCR    ───►   Estrazione NER   ───►   Chunking +    ───►   Riassunti AI
  (grezzo)           (LLM + C Rules)        (BERT fine-tuned)        Capitoli            (Ollama SLM)
```

Il dataset incluso contiene **95 testi** della letteratura italiana (Orlando Furioso, Divina Commedia, Promessi Sposi, Decameron, Leopardi, Machiavelli, Goldoni, Tasso, Vasari e altri).

---

## Architettura

```
┌────────────────────────────────────────────────────┐
│                  Docker Compose                    │
│                                                    │
│  ┌──────────────────┐        ┌──────────────────┐  │       ┌────────────────────┐
│  │    Frontend      │        │     Backend      │  │       │      Ollama        │
│  │   (Angular 21)   │        │    (FastAPI)     │  │       │  (qwen3.5:9b)      │
│  │                  │        │                  │  │       │                    │
│  │  Dashboard       │        │  REST API        │  │       │  SLM esterno per:  │
│  │  Analisi NER     │───────►│  Pipeline Engine │──┼──────►│  • pulizia OCR     │
│  │  Lettore Capitoli│        │  SQLite DB       │  │       │  • embeddings      │
│  │  Riassunti       │        │  File I/O        │  │       │  • riassunti       │
│  │                  │        │                  │  │       │                    │
│  │  :80 (nginx)     │        │  :8000 (uvicorn) │  │       │  (Host/LAN/Cloud)  │
│  └──────────────────┘        └──────────────────┘  │       └────────────────────┘
└────────────────────────────────────────────────────┘
```

| Componente | Ruolo |
|---|---|
| **Frontend** | SPA Angular con dashboard, viewer con evidenziazione entità, grafici NER e lettore di riassunti |
| **Backend** | API FastAPI che orchestra la pipeline, gestisce il database SQLite e serve i dati al frontend |
| **Ollama** | Server SLM esterno che esegue `qwen3.5:9b` per pulizia OCR e riassunti, e `bge-m3` per gli embedding semantici |

---

## La Pipeline

### Fase 1 — Pulizia OCR

La pulizia avviene in **due passaggi** complementari: un LLM per le correzioni contestuali e un programma C compilato per le regole deterministiche.

#### 1a. LLM Cleaner (Ollama)

Il testo viene diviso in chunk da ~1500 caratteri e inviato a `qwen3.5:9b` con un prompt specializzato in filologia italiana. Il modello restituisce un array JSON di correzioni:

```json
[
  {"errato": "disse il paladin o riandò verso", "corretto": "disse il paladino Orlando verso"},
  {"errato": "L udovico Ariosto", "corretto": "Ludovico Ariosto"}
]
```

Le correzioni vengono applicate tramite sostituzione nel testo originale. Parametri: `temperature: 0.0` (output rigorosamente deterministico tramite Greedy Decoding) e `seed: 42` (per i tie-breaker di probabilità), timeout 600s per chunk.

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

#### 3a. Chunking Semantico (Metodo Embed)

Utilizza il modello di embedding `bge-m3` eseguito localmente tramite **Ollama** per segmentare il testo in base al contenuto semantico, non alla lunghezza arbitraria.

1. Il testo viene diviso in paragrafi
2. Ogni paragrafo viene convertito in un embedding vettoriale tramite Ollama (`/api/embed`)
3. Si calcola la similarità coseno tra paragrafi consecutivi
4. Dove la similarità scende sotto la soglia (0.5), si inserisce un confine di chunk
5. Vengono anche rilevati i confini espliciti nel testo (`CAPITOLO`, `CANTO`, `LIBRO`, `PARTE` + numerali romani/arabi)
6. Ogni chunk risultante contiene: testo, offset nel documento, suggerimento di argomento (`topic_hint`) e le entità NER presenti

#### 3a-bis. Chunking Semantico (Metodo NER)

Metodo alternativo basato sull'overlap di entità NER tra blocchi consecutivi:
1. Il testo viene diviso in blocchi da 2000 caratteri
2. Per ogni coppia di blocchi adiacenti, si calcola l'indice di Jaccard sulle entità condivise
3. Dove l'overlap scende sotto soglia, si inserisce un confine
4. L'interfaccia web permette di confrontare i risultati dei due metodi con un report TF-IDF

#### 3b. Raggruppamento Capitoli Semantici

I chunk semantici vengono raggruppati in **capitoli semantici** in base al loro `topic_hint`: chunk consecutivi con lo stesso argomento di base (es. tutti i sotto-chunk di `"Capitolo Semantico 5"`) vengono uniti in un unico capitolo. Se il testo contiene capitoli espliciti (es. `CAPITOLO I`), questi vengono rispettati come confini naturali. Il risultato è un insieme di capitoli semantici con numero variabile di chunk (mediamente 5–15 chunk per capitolo).

### Fase 4 — Riassunti AI (Sinossi Globale)

La fase 4 implementa una **Hierarchical Summarization** con architettura **Map-Reduce a 4 livelli** per produrre la Sinossi Globale dell'opera.

#### Architettura della pipeline di riassunto

Per libri brevi (≤ 10 capitoli), la sinossi viene generata direttamente dai riassunti dei capitoli. Per libri lunghi (> 10 capitoli), viene attivata una pipeline Map-Reduce a più livelli per evitare il "recency bias" del modello (la tendenza a dimenticare le parti iniziali del testo quando il contesto è troppo lungo).

```
 ~1000 chunk semantici
         │
         ▼ (raggruppamento per topic_hint)
 ~200 capitoli semantici
         │
         ▼ (Livello 1: 1 chiamata Ollama per capitolo, compressione ~50%)
 ~200 riassunti di capitolo
         │
         ▼ (Livello 2: raggruppamento in blocchi da 10)
  ~20 macro-capitoli                     ← solo per libri lunghi (>10 capitoli)
         │
         ▼ (Livello 3: raggruppamento in blocchi da 4)
  ~5 riassunti parziali                  ← ogni blocco genera una porzione narrativa
         │
         ▼ (concatenazione)
 Sinossi globale dell'opera
```

#### Dettagli tecnici

- **Modello unificato**: `qwen3.5:9b` via Ollama (esecuzione esterna/locale, zero costi API)
- **Contesto per capitolo**: 16.384 token con output illimitato
- **Contesto per sinossi globale**: 65.536 token con output illimitato
- **Soglia macro-capitoli**: `MACRO_THRESHOLD = 10` (libri con più di 10 capitoli attivano la fase intermedia)
- **Dimensione macro-capitolo**: `MACRO_BATCH_SIZE = 10` (ogni macro-capitolo raggruppa 10 riassunti consecutivi)
- **Dimensione batch globale**: `GLOBAL_BATCH_SIZE = 4` (ogni riassunto parziale copre 4 macro-capitoli)
- **Esecuzione**: sequenziale per evitare saturazione VRAM

#### Metrica di valutazione: NER Retention

Per ogni capitolo viene calcolata la **NER Retention**: la percentuale di entità `PER` e `LOC` presenti nel testo originale che compaiono anche nel riassunto generato. Questa metrica misura quanto il modello preserva i nomi storicamente rilevanti durante la sintesi.

```
NER Retention = (entità sopravvissute nel riassunto) / (entità totali nel testo) × 100
```

Oltre alla retention per singolo capitolo, viene calcolata anche la **NER Retention Globale**: quante delle entità uniche dell'intero libro compaiono nella sinossi globale. Nell'interfaccia web è visualizzata con un badge colorato (🟢 ≥60%, 🟡 ≥35%, 🔴 <35%).

---

## Valutazione della Pipeline

Per evitare costi ripetuti con le API di Claude durante i test automatici, l'architettura di valutazione separa la **generazione dei Gold Standard** dall'**esecuzione dei test**.

### Valutazione NER (Fase 2)

```
scripts/generate_ner_gold.py          ← eseguito MANUALMENTE (chiama Claude + BERT)
         │
         └─► tests/evaluations/results/ner_evaluation_results.json   ← versionato su git
                      │
                      └─► tests/evaluations/test_phase2_ner.py        ← pytest (zero API, < 5s)
```

**1. Generare (o aggiornare) il gold standard NER**
Richiede la chiave Anthropic nel `.env`.
```bash
python3 scripts/generate_ner_gold.py --files 20
```

**2. Eseguire i test**
```bash
cd tests
python3 -m pytest -v -s evaluations/test_phase2_ner.py
```

| Metrica | Valore | Soglia minima |
|---------|:------:|:-------------:|
| **Precision** | 0.77 | 0.60 |
| **Recall** | 0.65 | 0.50 |
| **F1-Score** | 0.70 | — |

---

### Valutazione Chunking Semantico (Fase 3)

La fase 3 viene valutata confrontando i confini dei capitoli semantici individuati localmente (tramite embedding `bge-m3` via Ollama + Regex) con i confini individuati da Claude su un campione di paragrafi (es. "I Promessi Sposi"). Viene applicata una **tolleranza di $\pm 2$ paragrafi**.

```
scripts/generate_chunking_gold.py     ← eseguito MANUALMENTE (chiama Claude)
         │
         └─► tests/evaluations/results/chunking_evaluation_results.json
                      │
                      └─► tests/evaluations/test_phase3_chunking.py   ← pytest
```

**1. Generare (o aggiornare) il gold standard Chunking**
```bash
python3 scripts/generate_chunking_gold.py --book promessi_sposi-cleaned.json --paras 250
```

**2. Eseguire i test**
```bash
cd tests
python3 -m pytest -v -s evaluations/test_phase3_chunking.py
```

| Metrica | Valore | Soglia minima |
|---------|:------:|:-------------:|
| **Precision** | 0.50 | 0.45 |
| **Recall** | 1.00 | 0.60 |
| **F1-Score** | 0.67 | — |

> Il modello vettoriale ha una Recall del 100% (individua **tutti** i macro-capitoli di Claude), ma tende a "sovra-segmentare" leggermente i testi rispetto a un umano/LLM (Precision ~50%). Questo comportamento è atteso e desiderato per mantenere i blocchi piccoli prima del taglio forzato a 2000 caratteri.

### Valutazione Chunking NER (Alternativa)

Per fini comparativi, è stata creata anche un'architettura di test per valutare il **Metodo NER**.
Questo test divide il testo in blocchi fissi da 2000 caratteri e valuta la capacità dell'algoritmo (Jaccard Index sulle entità) di trovare i cambi di scena rispetto a un umano/LLM. La tolleranza applicata è di **$\pm 1$ blocco**.

```bash
# Per aggiornare il gold standard NER Chunking
python3 scripts/generate_ner_chunking_gold.py --book promessi_sposi-cleaned.json --ner 45e11373_promessi_sposi.txt_entities.json --blocks 50

# Per eseguire i test
cd tests
python3 -m pytest -v -s evaluations/test_phase3_ner_chunking.py
```

| Metrica | Valore | Soglia minima |
|---------|:------:|:-------------:|
| **Precision** | 0.52 | 0.40 |
| **Recall** | 0.58 | 0.40 |
| **F1-Score** | 0.55 | — |

> **Analisi Comparativa:** L'F1-Score del Metodo NER (0.55) è chiaramente inferiore a quello del Metodo Vettoriale Embed (0.67). Questo dimostra scientificamente perché il Metodo Embed è stato scelto come default per l'applicazione: la segmentazione vettoriale sui pseudo-paragrafi è molto più accurata della segmentazione a blocchi basata sui personaggi.

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

Accessibile cliccando "Analizza libro", offre 5 sezioni navigabili:

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
- **Sinossi Globale** con statistiche: caratteri, parole, tempo di lettura, modello usato, NER retention %
- Lista capitoli con indicatore ✅/○ (riassunto presente/assente)
- Testo del riassunto narrativo generato da Ollama
- Navigazione Precedente/Successivo
- Switcher tra modelli diversi (se disponibili)

#### 📊 Confronto Chunking
Report scientifico comparativo tra i metodi di chunking (Embed vs NER):
- Statistiche per metodo: numero chunk, lunghezza media, entità medie
- Profilo di similarità TF-IDF (intra-sezione, al confine, cross-sezione)
- Delta di nitidezza del taglio
- Distribuzione visuale dei chunk

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
│   │   ├── dependencies.py           # Dipendenze condivise (get_db, get_book_or_404)
│   │   ├── utils.py                  # Utilità condivise (extract_text_content, utcnow_iso)
│   │   ├── routers/
│   │   │   ├── books.py              # CRUD libri, upload, export ZIP
│   │   │   ├── pipeline.py           # Avvio fasi pipeline + progress + report chunking
│   │   │   ├── data.py               # Endpoint di lettura dati (testo, NER, chunk)
│   │   │   └── settings.py           # Configurazione runtime Ollama
│   │   └── pipeline/
│   │       ├── ollama_client.py       # Client centralizzato Ollama (generate, embed)
│   │       ├── ocr.py                # Pulizia OCR tramite Ollama
│   │       ├── ner.py                # Pipeline NER con BERT fine-tuned
│   │       ├── ner_chunking.py       # Utilità di segmentazione testo per NER
│   │       ├── chunker.py            # Chunking semantico (embed + NER)
│   │       └── summarizer.py         # Hierarchical Summarization
│   ├── data/
│   │   └── raw/                      # Testi italiani digitalizzati
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/                         # SPA Angular 21
│   ├── src/app/
│   │   ├── models/
│   │   │   └── models.ts             # Interfacce TypeScript condivise
│   │   ├── components/
│   │   │   ├── dashboard/            # Dashboard: upload, pipeline, anteprima
│   │   │   ├── analysis/             # Shell di analisi con tab navigation
│   │   │   │   ├── ocr-view/         # Vista pulizia OCR
│   │   │   │   ├── ner-view/         # Vista entità NER con Chart.js
│   │   │   │   ├── reader-view/      # Lettore capitoli con evidenziazione
│   │   │   │   ├── summaries-view/   # Navigatore riassunti + sinossi globale
│   │   │   │   └── compare-view/     # Report comparativo chunking
│   │   │   └── api-config/           # Modale configurazione Ollama
│   │   └── services/
│   │       ├── api.service.ts        # Client HTTP tipizzato per tutte le API
│   │       └── book-state.service.ts # Stato globale con Angular Signals
│   ├── Dockerfile
│   └── nginx.conf
│
├── scripts/                          # Script di utilità (eseguiti manualmente)
│   ├── generate_ner_gold.py          # Genera il gold standard NER (Claude + BERT)
│   ├── generate_chunking_gold.py     # Genera gold standard Chunking (Claude)
│   └── generate_ner_chunking_gold.py # Genera gold standard per Chunking NER
│
├── tests/                            # Suite di test (pytest)
│   ├── evaluations/
│   │   ├── results/                  # Gold standard versionati (zero API per i test)
│   │   ├── test_phase2_ner.py
│   │   ├── test_phase3_chunking.py
│   │   ├── test_phase3_ner_chunking.py
│   │   └── test_phase4_summaries.py
│   └── utils/
│       └── anthropic_client.py       # Client Anthropic per la generazione gold
│
├── docker-compose.yml                # 2 servizi: backend + frontend

```

---

## Prerequisiti

| Strumento | Versione minima | Utilizzo |
|-----------|:-:|---|
| **Docker + Docker Compose** | — | ✅ Raccomandato: avvia tutto con un solo comando |
| **Python** | 3.10+ | Solo per sviluppo locale senza Docker |
| **Node.js** | 18+ | Solo per sviluppo locale senza Docker |
| **GCC + Make** | — | Solo per sviluppo locale senza Docker |
| **Ollama** | — | Necessario (locale, LAN o remoto). Non incluso in Docker |

> **🚀 Consiglio**: Usa **Docker Compose** (`docker compose up --build`) per avviare frontend e backend con un solo comando. Ollama deve essere avviato separatamente.


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
cd backend/app/pipeline/c_cleaner
make
cd ../../../..
```

Produce il binario `backend/app/pipeline/c_cleaner/bin/ocr_cleaner`.

#### 3. Configura le variabili d'ambiente

```bash
cp env.example .env
# Modifica .env con il tuo editor
```

#### 4. Installa e avvia Ollama

```bash
# Installa Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Scarica il modello unificato SLM
ollama pull qwen3.5:9b
# Modello di embedding semantico
ollama pull bge-m3
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

Avvia backend e frontend in due terminali separati:

```bash
# Terminale 1 — Backend
cd backend && source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminale 2 — Frontend
cd frontend && npm start
```

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

Funziona subito, senza configurazione. Tutte le variabili d'ambiente hanno valori di default nel `docker-compose.yaml`.

> **⚙️ Personalizzazione (opzionale):** Se Ollama è su un altro PC in rete, crea un file `.env` per sovrascrivere i default:
> ```bash
> cp env.example .env
> # Modifica OLLAMA_HOST con l'IP del server Ollama
> ```

L'architettura in Docker Compose non include Ollama per mantenere snello il deploy. Ollama deve essere in esecuzione separatamente (sulla stessa macchina, in LAN o in remoto).

| Servizio | URL |
|---|---|
| Frontend | http://localhost |
| API Backend | http://localhost:8000 |

> **💡 Note sui download AI**: Il progetto usa una logica "fault-tolerant": se Ollama non è raggiungibile, le fasi che lo richiedono riporteranno un avviso o si appoggeranno ad alternative deterministiche (es. la pulizia salterà il passaggio LLM e passerà direttamente alle regole in C). L'Intelligenza Artificiale necessaria per il NER (modello BERT da ~450MB) verrà scaricata automaticamente dal backend Python **solo quando avvierai la primissima analisi di un libro**.

---

## Configurazione

Tutte le impostazioni sono gestite tramite variabili d'ambiente nel file `.env`:

```env
# ── Ollama (SLM per pulizia OCR e riassunti) ─────────────
OLLAMA_HOST=localhost              # IP/hostname del server Ollama (es. http://192.168.1.55)
OLLAMA_PORT=11434
OLLAMA_MODEL=qwen3.5:9b           # Modello SLM unificato per tutte le fasi (pulizia e riassunti)

# ── NER ───────────────────────────────────────────────────
NER_MODEL_NAME=aendriu/bert-ner-italian-historical
NER_SCORE_THRESHOLD=0.65          # Soglia confidenza (0.0–1.0)
NER_MIN_ENTITY_CHARS=3            # Lunghezza minima entità

# ── Chunking Semantico (embedding via Ollama) ────────────
SEMANTIC_EMBEDDING_MODEL=bge-m3   # Modello di embedding eseguito su Ollama
SEMANTIC_SIMILARITY_THRESHOLD=0.5 # Soglia per confini di chunk

# ── Database ──────────────────────────────────────────────
DB_FILENAME=historicbooks.db

# ── Testing (opzionale) ───────────────────────────────────
ANTHROPIC_API_KEY=                # Solo per generare i gold standard di test
ANTHROPIC_MODEL=claude-sonnet-5   # Modello Claude per la generazione gold
```

---

## Il Database (SQLite)

Il progetto utilizza **SQLite** (`historicbooks.db`) tramite SQLAlchemy per l'orchestrazione.
Il database **non memorizza i testi interi o le entità** (che peserebbero gigabyte e sono salvati come file JSON), ma agisce come un "quadro di comando" che tiene traccia dello stato di avanzamento e dei metadati.

Il database contiene 3 tabelle principali (relazionali):

1. **`books`**: Rappresenta un libro caricato.
   - Tiene traccia dello stato della pipeline (`UPLOADED`, `OCR_CLEANING`, `NER_EXTRACTION`, `SEMANTIC_CHUNKING`, `COMPLETED`, ecc.).
   - Salva i **percorsi assoluti** ai file sul disco rigido (es. `clean_file_path`, `ner_file_path`) funzionando come un indice per il filesystem locale.
2. **`chapters`**: Collegata 1-a-N con `books`.
   - Memorizza i metadati dei capitoli (titolo, numero).
   - Salva i confini di testo (`char_start`, `char_end`) per estrarre velocemente il testo di un capitolo specifico senza leggere l'intero JSON.
3. **`summaries`**: Collegata 1-a-1 con `chapters`.
   - Memorizza il testo effettivo dei riassunti generati dall'AI, rendendoli interrogabili e collegandoli istantaneamente al frontend senza dover leggere la cartella dei riassunti.

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
│   └── capitoli.json                       # Manifest dei capitoli semantici
└── 05_riassunti/
    ├── summaries.json                      # Riassunti + sinossi globale + NER retention
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
  "total_chunks": 996,
  "text": "Quel ramo del lago di Como...",
  "char_start": 52340,
  "char_end": 54280,
  "topic_hint": "Capitolo Semantico 12",
  "entities": [
    {"word": "Como", "label": "LOC", "score": 0.95}
  ]
}
```

### Formato Riassunti (summaries.json)

```json
{
  "book_name": "promessi_sposi",
  "method": "embed",
  "model": "qwen3.5:9b",
  "created_at": "2026-07-12T10:00:00",
  "total_sections": 115,
  "avg_ner_retention": 72.4,
  "global_summary": "I Promessi Sposi narra la storia di Renzo e Lucia...",
  "sections": [
    {
      "section_idx": 1,
      "topic_hint": "Il paesaggio del lago di Como",
      "num_chunks": 4,
      "summary": "...",
      "ner_retention": {
        "retention_percent": 85.7,
        "total_key_entities": 7,
        "survived": ["Como", "Lecco", "Adda"],
        "lost": ["Resegone"]
      }
    }
  ]
}
```

---

## Tecnologie

| Strato | Tecnologia | Utilizzo |
|---|---|---|
| **Backend API** | FastAPI + Uvicorn | Server REST asincrono |
| **Database** | SQLite + SQLAlchemy | Storage libri, capitoli, riassunti |
| **Pulizia OCR (AI)** | Ollama + Qwen 3.5 9B | Correzione contestuale errori OCR |
| **Pulizia OCR (regole)** | C nativo (gcc) | Euristiche deterministiche ad alte prestazioni |
| **NER** | BERT fine-tuned (`aendriu/bert-ner-italian-historical`) | Estrazione entità storiche italiane |
| **Embeddings** | Ollama + BGE-M3 | Segmentazione semantica del testo |
| **Riassunti** | Ollama + Qwen 3.5 9B | Hierarchical Summarization |
| **Frontend** | Angular 21 (standalone, signals) | Interfaccia web SPA |
| **Grafici** | Chart.js 4.5 | Visualizzazione distribuzione entità |
| **Web Server** | Nginx | Serving SPA + reverse proxy API |
| **Container** | Docker Compose | Deploy con 2 servizi orchestrati |
| **ML Runtime** | PyTorch + HuggingFace Transformers | Inferenza modello NER |
| **Testing Gold** | Anthropic Claude (solo script offline) | Generazione gold standard per valutazione |
