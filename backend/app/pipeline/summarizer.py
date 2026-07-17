"""
Hierarchical Summarization — Map-Reduce Gerarchico a 4 Livelli
Strategia a piramide adattiva per SLM locali (via Ollama).

Architettura a 4 livelli:

  Livello 1 — Riassunti delle Sezioni Semantiche:
    Per ogni sezione semantica (= capitolo), genera un resoconto
    narrativo fedele al testo (~50% compressione). Se la sezione è
    troppo lunga, la divide in batch e fonde i sub-resoconti.

  Livello 2 — Macro-Capitoli (solo per libri lunghi, >MACRO_THRESHOLD sezioni):
    Raggruppa i riassunti in blocchi di MACRO_BATCH_SIZE e genera
    un riassunto intermedio per ogni blocco.

  Livello 3 — Sinossi Parziali (solo se >GLOBAL_BATCH_SIZE macro-capitoli):
    Raggruppa i macro-capitoli in blocchi di GLOBAL_BATCH_SIZE e genera
    segmenti narrativi indipendenti per evitare il recency bias.

  Livello 4 — Sinossi Globale:
    Concatenazione dei segmenti parziali (o sinossi diretta se il libro
    è breve) per produrre la sinossi finale dell'intera opera.

Controllo NER: cerca le entità originali (PER, LOC) nel testo
del riassunto via semplice text matching (nessun overhead NLP).
"""

import os
import json
import logging
import re
import requests
from datetime import datetime
from typing import Callable

from app.config import settings

logger = logging.getLogger(__name__)

# ─── Costanti ─────────────────────────────────────────────────────────────────
MAX_CHARS_PER_CALL = 20_000   # max caratteri di input per singola chiamata LLM

# Lv 0 — resoconti delle sezioni semantiche (verbosità massima)
NUM_CTX_SECTION     = 16_384  # contesto ampio per permettere output prolisso
NUM_PREDICT_SECTION =  -1  # -1 = illimitato (nessun troncamento prematuro)

# Lv 1/2 — macro-capitoli e sinossi globale
NUM_CTX_GLOBAL     = 65_536
NUM_PREDICT_GLOBAL =  -1   # -1 = illimitato

# Map-Reduce: soglia e dimensione dei macro-capitoli
MACRO_THRESHOLD  = 10   # numero minimo di sezioni per attivare la fase intermedia
MACRO_BATCH_SIZE = 10   # quante sezioni raggruppare in un macro-capitolo
GLOBAL_BATCH_SIZE = 4   # quanti macro-capitoli processare per ogni riassunto parziale

# ─── Ollama helper ────────────────────────────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """Rimuove i blocchi <think>...</think> generati da modelli Qwen3 in thinking mode."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def _call_ollama(
    prompt: str,
    *,
    num_ctx: int     = NUM_CTX_SECTION,
    num_predict: int = NUM_PREDICT_SECTION,
    temperature: float = 0.1,
    timeout: int     = 480,
) -> str:
    """Singola chiamata all'API Ollama con streaming.

    Args:
        prompt:      testo del prompt da inviare al modello.
        num_ctx:     dimensione della finestra di contesto (token).
        num_predict: numero massimo di token da generare in output.
        temperature: temperatura di campionamento.
        timeout:     timeout della richiesta HTTP in secondi.
    """
    host = settings.OLLAMA_HOST.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}:{settings.OLLAMA_PORT}"
    url = f"{host}/api/generate"

    try:
        r = requests.post(
            url,
            json={
                "model":   settings.OLLAMA_MODEL,
                "prompt":  prompt,
                "stream":  True,
                "think":   False,   # disabilita thinking Qwen3 (top-level flag)
                "options": {
                    "temperature": temperature,
                    "num_ctx":     num_ctx,
                    "num_predict": num_predict,
                },
            },
            stream=True,
            timeout=timeout,
        )
        r.raise_for_status()
        parts = []
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                parts.append(chunk.get("response", ""))
                if chunk.get("done", False):
                    break
            except json.JSONDecodeError:
                continue
        raw    = "".join(parts)
        result = _strip_thinking(raw)
        if not result:
            preview = raw[:300].replace("\n", "↵") if raw else "<STRINGA VUOTA>"
            logger.warning(f"Risposta vuota dopo strip. Raw preview: {preview}")
        return result
    except Exception as e:
        logger.error(f"Errore chiamata Ollama: {e}")
        return ""


def _strip_markdown(text: str) -> str:
    """Rimuove aggressivamente qualsiasi formattazione markdown dall'output LLM.

    Questa funzione è necessaria perché i modelli SLM piccoli (es. Qwen 9B)
    tendono a ignorare le istruzioni di formato e producono comunque
    intestazioni, grassetti, elenchi puntati, ecc.
    """
    if not text:
        return text
    # Rimuovi intestazioni markdown (# ## ### ecc.)
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    # Rimuovi grassetti e corsivi (**testo**, *testo*, __testo__, _testo_)
    text = re.sub(r'\*{1,3}([^*]+)\*{1,3}', r'\1', text)
    text = re.sub(r'_{1,3}([^_]+)_{1,3}', r'\1', text)
    # Rimuovi elenchi puntati (- testo, * testo, • testo)
    text = re.sub(r'^\s*[-*•►]\s+', '', text, flags=re.MULTILINE)
    # Rimuovi elenchi numerati (1. testo, 2. testo ecc.)
    text = re.sub(r'^\s*\d+\.\s+', '', text, flags=re.MULTILINE)
    # Rimuovi separatori markdown (---, ***)
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Collassa righe vuote consecutive (max 2)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


# ─── Prompt builder ───────────────────────────────────────────────────────────

def _prompt_section_batch(text: str, entities_str: str) -> str:
    """Prompt per il riassunto di un frammento di testo (Livello 1).

    Obiettivo: comprimere il testo al ~50% della lunghezza originale,
    mantenendo gli eventi principali, i personaggi e la trama.
    """
    target_chars = max(len(text) // 2, 300)
    return f"""Sei un narratore fedele al testo. Il tuo unico compito è riassumere questo frammento.

Personaggi e luoghi presenti nel testo: {entities_str}

REGOLA 1 — ANTI-ALLUCINAZIONE (la più importante):
- Usa SOLO i nomi di personaggi, luoghi ed eventi che compaiono nel testo qui sotto.
- Copia i nomi ESATTAMENTE come sono scritti. Non inventare varianti, soprannomi o nomi nuovi.
- Se un fatto non è nel testo, NON includerlo.

REGOLA 2 — VIETATO FARE ANALISI LETTERARIA:
- Non scrivere frasi come "il testo esplora", "simboleggia", "l'autore vuole dimostrare",
  "questo episodio rappresenta", "funge da specchio", "il narratore riflette".
- Racconta SOLO cosa succede: chi fa cosa, dove, quando e perché.

REGOLA 3 — FORMATO:
- COMPRIMI il testo: il tuo riassunto deve essere circa {target_chars} caratteri (circa il 50% del testo originale).
- Scrivi in prosa continua e fluida.
- VIETATO: elenchi puntati, titoli, grassetti, corsivi, cancelletti, simboli markdown.
- Rispondi SOLO con il testo del riassunto, senza preamboli.

TESTO:
{text}
"""


def _prompt_merge_summaries(summaries: list[str], title: str) -> str:
    """Prompt per unificare riassunti parziali di una sezione."""
    joined = "\n\n".join(f"Parte {i+1}:\n{s}" for i, s in enumerate(summaries))
    return f"""Sei un narratore fedele al testo. Unifica i seguenti riassunti parziali della sezione "{title}" in un unico testo coeso.

REGOLA 1 — ANTI-ALLUCINAZIONE:
- Usa SOLO i nomi e i fatti presenti nei riassunti qui sotto.
- Non aggiungere eventi, personaggi o dettagli inventati.
- Copia i nomi ESATTAMENTE come sono scritti.

REGOLA 2 — VIETATO FARE ANALISI LETTERARIA:
- Non scrivere "il testo esplora", "simboleggia", "l'autore vuole dimostrare".
- Racconta SOLO i fatti.

REGOLA 3 — FORMATO:
- Mantieni gli eventi nell'ordine narrativo corretto.
- Elimina ripetizioni. Il risultato deve essere più breve della somma delle parti.
- VIETATO: elenchi, trattini, titoli, grassetti, corsivi, cancelletti, markdown.
- Rispondi SOLO con il testo unificato, senza preamboli.

RIASSUNTI PARZIALI:
{joined}
"""


def _clean_book_name(book_name: str) -> str:
    """Pulisce il nome del libro: rimuove hash iniziale, estensione, underscores."""
    clean = re.sub(r'^[0-9a-f]{6,}_', '', book_name)
    return clean.replace('_', ' ').replace('.txt', '').replace('.json', '').strip().title()


def _prompt_global_summary(book_name: str, chapter_summaries: list[str], original_total_chars: int = 0) -> str:
    """Prompt per la sinossi globale dell'intera opera.

    Riceve i riassunti dei macro-capitoli (o delle sezioni dirette se il libro
    è breve) e chiede all'LLM di produrre una panoramica fedele e narrativa.
    """
    clean_name = _clean_book_name(book_name)
    n = len(chapter_summaries)
    joined = "\n\n".join(f"--- Sezione {i+1}/{n} ---\n{s}" for i, s in enumerate(chapter_summaries))
    # 33% del libro originale, con floor di 5000 caratteri
    min_output_chars = max(original_total_chars // 3, 5000) if original_total_chars else max(sum(len(s) for s in chapter_summaries) // 2, 5000)
    return f"""Sei un narratore esperto. Il tuo unico compito è raccontare la trama dell'opera "{clean_name}" in prosa continua.

REGOLA 1 — ANTI-ALLUCINAZIONE (la più importante):
- Usa SOLO i nomi di personaggi, luoghi ed eventi che compaiono esplicitamente nei riassunti qui sotto.
- Copia i nomi ESATTAMENTE come sono scritti. Non modificarli, non accorciarli, non inventare varianti.
- Se un fatto non è nei riassunti, NON includerlo.

REGOLA 2 — VIETATO FARE ANALISI LETTERARIA:
- Non scrivere frasi come "il romanzo esplora", "la figura di X simboleggia", "l'autore vuole dimostrare",
  "questo episodio rappresenta", "il testo offre un'analisi", "funge da specchio".
- Racconta i FATTI della trama in ordine cronologico, come un narratore, non come un critico letterario.

REGOLA 3 — COPERTURA OBBLIGATORIA DI TUTTE LE {n} SEZIONI:
- Devi coprire TUTTE le {n} sezioni nell'ordine in cui sono numerate (dalla Sezione 1 alla Sezione {n}).
- PARTI DALLA SEZIONE 1 e procedi in ordine fino alla Sezione {n}. Non saltare le prime sezioni.
- Ogni sezione deve produrre almeno un paragrafo nel testo finale.
- Il riassunto deve essere lungo almeno {min_output_chars} caratteri.

RIASSUNTI DELLE SEZIONI (unica fonte autorizzata):
{joined}

FORMATO (rispettare tassativamente):
- Prosa narrativa continua, paragrafi separati da righe vuote.
- VIETATO: elenchi, trattini, titoli, grassetti, corsivi, cancelletti, simboli markdown.
- Inizia subito con il racconto, senza preamboli o introduzioni.
"""


def _prompt_macro_chapter(book_name: str, chapter_summaries: list[str],
                           part_num: int, total_parts: int) -> str:
    """Prompt per il riassunto di un macro-capitolo."""
    clean_name = _clean_book_name(book_name)
    joined = "\n\n".join(f"--- Sezione {i+1} ---\n{s}" for i, s in enumerate(chapter_summaries))
    return f"""Sei un narratore esperto. Scrivi il riassunto della PARTE {part_num} di {total_parts} dell'opera "{clean_name}".

Questa parte comprende {len(chapter_summaries)} sezioni consecutive.

REGOLE:
- Usa SOLO i nomi di personaggi, luoghi ed eventi presenti nei riassunti qui sotto.
- Copia i nomi ESATTAMENTE come scritti. Non inventare varianti o soprannomi.
- Racconta i FATTI in ordine cronologico. Non fare analisi letteraria.
- Ogni sezione deve avere almeno un paragrafo nel tuo riassunto.
- Il riassunto deve essere lungo e dettagliato.

RIASSUNTI DELLE SEZIONI:
{joined}

FORMATO:
- Prosa narrativa continua, paragrafi separati da righe vuote.
- VIETATO: elenchi, trattini, titoli, grassetti, corsivi, cancelletti, markdown.
- Inizia subito col racconto.
"""


def _prompt_partial_global(book_name: str, macro_summaries: list[str],
                            part_num: int, total_parts: int,
                            global_section_start: int, global_section_end: int) -> str:
    """Prompt per un segmento del riassunto globale.

    Invece di generare l'intera sinossi in una chiamata, il riassunto
    viene costruito a blocchi di macro-capitoli. Ogni blocco produce
    un segmento narrativo autonomo che verrà poi concatenato.
    """
    clean_name = _clean_book_name(book_name)
    n = len(macro_summaries)
    joined = "\n\n".join(
        f"--- Macro-capitolo {global_section_start + i} ---\n{s}"
        for i, s in enumerate(macro_summaries)
    )

    if part_num == 1:
        position = "INIZIALE"
    elif part_num == total_parts:
        position = "FINALE"
    else:
        position = "CENTRALE"

    return f"""Sei un narratore esperto. Stai scrivendo il riassunto dell'opera "{clean_name}".
Questa è la PARTE {part_num} di {total_parts} (porzione {position} dell'opera).

Racconta in modo dettagliato e cronologico tutti i fatti contenuti nei macro-capitoli qui sotto.

REGOLA 1 — ANTI-ALLUCINAZIONE:
- Usa SOLO i nomi che trovi nei riassunti. Non inventare, non modificare, non fondere nomi di personaggi.
- Se un nome è "Renzo Tramaglino", scrivi "Renzo Tramaglino", non "Lorenzo", non "Antonio", non varianti.

REGOLA 2 — VIETATA L'ANALISI LETTERARIA:
- Non scrivere "il romanzo esplora", "simboleggia", "l'autore vuole dimostrare".
- Racconta solo cosa SUCCEDE ai personaggi.

REGOLA 3 — DETTAGLIO:
- Ogni macro-capitolo deve produrre diversi paragrafi.
- Non omettere eventi, dialoghi importanti o personaggi secondari.

MACRO-CAPITOLI (unica fonte autorizzata):
{joined}

FORMATO:
- Prosa narrativa continua, paragrafi separati da righe vuote.
- VIETATO: elenchi, trattini, titoli, grassetti, corsivi, cancelletti, markdown.
- Inizia subito col racconto.
"""


# ─── NER retention ────────────────────────────────────────────────────────────

def _calculate_ner_retention(original_entities: list[dict], summary_text: str) -> dict:
    """Verifica quante entità PER/LOC del testo originale sono menzionate nel riassunto.

    Usa semplice text matching (lower case) — nessun overhead NLP aggiuntivo.
    """
    key_entities: set[str] = set()
    for e in original_entities:
        label = e.get("label") or e.get("entity_group", "")
        if label in ("PER", "LOC"):
            word = e.get("word", "").replace("##", "").strip().lower()
            if len(word) >= 3:
                key_entities.add(word)

    if not key_entities:
        return {
            "retention_percent":  100.0,
            "total_key_entities": 0,
            "survived":           [],
            "lost":               [],
        }

    summary_lower = summary_text.lower()
    survived = [e for e in key_entities if e in summary_lower]
    lost     = [e for e in key_entities if e not in summary_lower]

    return {
        "retention_percent":  round(len(survived) / len(key_entities) * 100, 1),
        "total_key_entities": len(key_entities),
        "survived":           sorted(survived),
        "lost":               sorted(lost),
    }


# ─── Helper ───────────────────────────────────────────────────────────────────

def _extract_entities_str(chunks: list[dict]) -> str:
    """Estrae le entità PER/LOC uniche da una lista di chunk e le restituisce come stringa."""
    entities: set[str] = set()
    for c in chunks:
        for e in c.get("entities", []):
            label = e.get("label") or e.get("entity_group", "")
            if label in ("PER", "LOC"):
                w = e.get("word", "").replace("##", "").strip()
                if len(w) >= 3:
                    entities.add(w)
    return ", ".join(sorted(entities)) or "Nessuna entità specifica"


# ─── Summarizer per una singola sezione ──────────────────────────────────────

def _summarize_section(chunks: list[dict]) -> str:
    """Genera il resoconto esaustivo di una sezione semantica (Livello 0).

    Adatta automaticamente il numero di chiamate Ollama alla lunghezza del testo.
    """
    if not chunks:
        return ""

    full_text    = "\n\n".join(c.get("text", "") for c in chunks)
    entities_str = _extract_entities_str(chunks)

    # ── Caso semplice: testo breve → 1 sola chiamata ──
    if len(full_text) <= MAX_CHARS_PER_CALL:
        logger.info(f"  → Invio sezione a Ollama: {len(full_text)} char")
        return _strip_markdown(_call_ollama(_prompt_section_batch(full_text, entities_str)))

    # ── Caso piramide: testo lungo → batch → merge ──
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars = 0

    for chunk in chunks:
        clen = len(chunk.get("text", ""))
        if current_chars + clen > MAX_CHARS_PER_CALL and current_batch:
            batches.append(current_batch)
            current_batch = [chunk]
            current_chars = clen
        else:
            current_batch.append(chunk)
            current_chars += clen
    if current_batch:
        batches.append(current_batch)

    # L1: sub-resoconti per ogni batch
    sub_summaries: list[str] = []
    for batch in batches:
        batch_text = "\n\n".join(c.get("text", "") for c in batch)
        e_str = _extract_entities_str(batch)
        sub   = _strip_markdown(_call_ollama(_prompt_section_batch(batch_text, e_str)))
        if sub:
            sub_summaries.append(sub)

    if not sub_summaries:
        return ""
    if len(sub_summaries) == 1:
        return sub_summaries[0]

    # L2: merge dei sub-resoconti
    title  = chunks[0].get("topic_hint", "Sezione").replace(" (parte)", "")
    merged = _strip_markdown(_call_ollama(_prompt_merge_summaries(sub_summaries, title)))
    return merged or " ".join(sub_summaries)


# ─── Entry point principale ───────────────────────────────────────────────────

def run_hierarchical_summarization(
    book_name:     str,
    method:        str,
    semantic_dir:  str,
    summaries_dir: str,
    progress_cb:   Callable | None = None,
    cancel_event=None,   # threading.Event — se settato il loop si ferma
) -> dict:
    """
    Esegue il processo completo di Hierarchical Summarization (Livello 0).

    Input:  {semantic_dir}/{method}_method/{book_name}/  (chunk JSON)
    Output: {summaries_dir}/{method}_method/{book_name}/summaries_{model}.json
    """
    method_subdir = "embed_method" if method == "embed" else "ner_method"
    base_dir      = os.path.join(semantic_dir, method_subdir, book_name)
    manifest_path = os.path.join(base_dir, "manifest.json")

    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest non trovato: {manifest_path}")

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    chunks_meta = manifest.get("chunks", [])
    if not chunks_meta:
        raise ValueError("Nessun chunk nel manifest.")

    # ── Raggruppa chunk per sezione semantica (stesso topic_hint base) ──
    # Es. "Capitolo Semantico 1" e "Capitolo Semantico 1 (parte)" → stessa sezione
    def _base_topic(topic: str) -> str:
        return re.sub(r"\s*\(parte.*?\)", "", topic).strip()

    sections: list[dict] = []
    for c_meta in chunks_meta:
        chunk_file = os.path.join(base_dir, f"chunk_{c_meta['chunk_id']:03d}.json")
        if not os.path.exists(chunk_file):
            continue
        with open(chunk_file, encoding="utf-8") as f:
            chunk_data = json.load(f)

        base_topic = _base_topic(chunk_data.get("topic_hint", "Sezione"))

        if sections and sections[-1]["topic"] == base_topic:
            sections[-1]["chunks"].append(chunk_data)
        else:
            sections.append({"topic": base_topic, "chunks": [chunk_data]})

    total_sections = len(sections)
    
    total_macros_est = 0
    total_global_batches_est = 1
    if total_sections > MACRO_THRESHOLD:
        total_macros_est = (total_sections + MACRO_BATCH_SIZE - 1) // MACRO_BATCH_SIZE
        if total_macros_est > GLOBAL_BATCH_SIZE:
            total_global_batches_est = (total_macros_est + GLOBAL_BATCH_SIZE - 1) // GLOBAL_BATCH_SIZE
    total_steps = total_sections + total_macros_est + total_global_batches_est

    if progress_cb:
        progress_cb(0, total_steps, f"Trovate {total_sections} sezioni semantiche.")

    # Calcola il totale dei caratteri originali del libro (per il target del riassunto globale)
    original_total_chars = sum(
        len(c.get("text", ""))
        for sec in sections
        for c in sec["chunks"]
    )

    # ── Percorso di output (nome file include il modello, per confronto tra LLM) ──
    _safe_model = re.sub(r"[^\w\-]", "_", settings.OLLAMA_MODEL)
    out_dir  = os.path.join(summaries_dir, method_subdir, book_name)
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"summaries_{_safe_model}.json")

    # ── Resume: carica resoconti già completati (solo quelli con summary non vuota) ──
    section_results: list[dict] = [None] * total_sections
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
            for r in existing.get("sections", []):
                idx_r = r.get("section_idx", 0) - 1
                if 0 <= idx_r < total_sections and r.get("summary", "").strip():
                    section_results[idx_r] = r
            already_done = sum(1 for r in section_results if r is not None)
            if already_done > 0:
                logger.info(f"Resume: trovate {already_done}/{total_sections} sezioni già completate — le salto.")
                if progress_cb:
                    progress_cb(already_done, total_steps,
                                f"Resume: {already_done}/{total_sections} sezioni già completate.")
        except Exception as e:
            logger.warning(f"Impossibile caricare resoconti parziali esistenti: {e}")

    def _save_partial():
        """Salva il file summaries.json con i risultati parziali finora completati."""
        valid_so_far = [r for r in section_results if r is not None]
        retentions   = [r["ner_retention"]["retention_percent"] for r in valid_so_far]
        partial_output = {
            "book_name":          book_name,
            "method":             method,
            "model":              settings.OLLAMA_MODEL,
            "created_at":         datetime.utcnow().isoformat(),
            "total_sections":     total_sections,
            "completed_sections": len(valid_so_far),
            "avg_ner_retention":  round(sum(retentions) / len(retentions), 1) if retentions else 0.0,
            "global_summary":     "",   # verrà popolato solo alla fine
            "sections":           valid_so_far,
        }
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(partial_output, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Errore salvataggio parziale: {e}")

    # ── Esecuzione sequenziale garantita (no ThreadPool: Ollama è single-thread sulla GPU) ──
    for idx, sec in enumerate(sections):
        if cancel_event is not None and cancel_event.is_set():
            logger.info(f"Cancellazione richiesta: fermo dopo la sezione {idx} ({idx}/{total_sections} completate).")
            break

        if section_results[idx] is not None:
            if progress_cb:
                progress_cb(idx + 1, total_steps,
                            f"[già fatto] Sezione {idx+1}/{total_sections}: {sec['topic']}")
            continue

        topic  = sec["topic"]
        chunks = sec["chunks"]

        if progress_cb:
            progress_cb(idx + 1, total_steps, f"Sezione {idx+1}/{total_sections}: {topic}")

        try:
            summary = _summarize_section(chunks)

            if not summary:
                logger.warning(f"Sezione {idx+1} ({topic}) — resoconto vuoto.")

            all_ents = [e for c in chunks for e in c.get("entities", [])]
            ner      = _calculate_ner_retention(all_ents, summary)

            section_results[idx] = {
                "section_idx":   idx + 1,
                "topic_hint":    topic,
                "num_chunks":    len(chunks),
                "total_chars":   sum(len(c.get("text", "")) for c in chunks),
                "summary":       summary,
                "ner_retention": ner,
            }
            _save_partial()

            logger.info(
                f"Sezione {idx+1}/{total_sections} salvata — "
                f"NER retention: {ner['retention_percent']}% "
                f"(lost: {ner['lost']})"
            )
        except Exception as e:
            logger.error(f"Sezione {idx+1} — errore non gestito: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # SINOSSI GLOBALE — Map-Reduce gerarchico
    # ══════════════════════════════════════════════════════════════════════════
    #
    # Per libri brevi (≤ MACRO_THRESHOLD sezioni):
    #   sezioni → sinossi (1 sola chiamata)
    #
    # Per libri lunghi (> MACRO_THRESHOLD sezioni):
    #   sezioni → macro-capitoli (gruppi di MACRO_BATCH_SIZE) → sinossi
    #
    # ══════════════════════════════════════════════════════════════════════════

    if progress_cb:
        progress_cb(total_sections, total_steps, "Analisi sezioni completata...")

    chapter_summaries = [
        r["summary"] for r in section_results
        if r is not None and r.get("summary")
    ]

    if len(chapter_summaries) <= MACRO_THRESHOLD:
        logger.info(f"Libro breve ({len(chapter_summaries)} sezioni ≤ {MACRO_THRESHOLD}): sinossi diretta.")
        if progress_cb:
            progress_cb(total_sections, total_steps,
                        f"Sinossi diretta da {len(chapter_summaries)} sezioni...")
        input_summaries = chapter_summaries
    else:
        total_macros = (len(chapter_summaries) + MACRO_BATCH_SIZE - 1) // MACRO_BATCH_SIZE
        logger.info(
            f"Libro lungo ({len(chapter_summaries)} sezioni > {MACRO_THRESHOLD}): "
            f"Map-Reduce con {total_macros} macro-capitoli (batch da {MACRO_BATCH_SIZE})."
        )

        macro_summaries: list[str] = []
        for i in range(0, len(chapter_summaries), MACRO_BATCH_SIZE):
            batch    = chapter_summaries[i:i + MACRO_BATCH_SIZE]
            part_num = i // MACRO_BATCH_SIZE + 1

            if progress_cb:
                progress_cb(total_sections + part_num, total_steps,
                            f"Macro-capitolo {part_num}/{total_macros} "
                            f"(sezioni {i+1}–{i+len(batch)})...")

            macro = _strip_markdown(_call_ollama(
                _prompt_macro_chapter(book_name, batch, part_num, total_macros),
                num_ctx=NUM_CTX_GLOBAL,
                num_predict=NUM_PREDICT_GLOBAL,
                temperature=0.05,
                timeout=600,
            ))
            if macro:
                macro_summaries.append(macro)
                logger.info(f"Macro-capitolo {part_num}/{total_macros} completato ({len(macro)} char).")
            else:
                logger.warning(f"Macro-capitolo {part_num}/{total_macros} vuoto.")

        input_summaries = macro_summaries

    # ══════════════════════════════════════════════════════════════════════════
    # FASE FINALE: Generazione riassunto globale A BLOCCHI
    # Invece di una singola chiamata con tutti i macro-capitoli (che causa
    # recency bias e perdita dei primi capitoli), generiamo riassunti parziali
    # per gruppi di macro-capitoli e li concateniamo.
    # ══════════════════════════════════════════════════════════════════════════

    if len(input_summaries) <= GLOBAL_BATCH_SIZE:
        # Pochi macro-capitoli: una sola chiamata basta
        logger.info(f"Sinossi diretta da {len(input_summaries)} macro-capitoli.")
        if progress_cb:
            progress_cb(total_sections + total_macros_est + 1, total_steps,
                        "Generazione sinossi globale...")
        global_summary = _strip_markdown(_call_ollama(
            _prompt_global_summary(book_name, input_summaries, original_total_chars),
            num_ctx=NUM_CTX_GLOBAL,
            num_predict=NUM_PREDICT_GLOBAL,
            temperature=0.05,
            timeout=900,
        ))
    else:
        # Molti macro-capitoli: generiamo a blocchi e concateniamo
        total_global_batches = (len(input_summaries) + GLOBAL_BATCH_SIZE - 1) // GLOBAL_BATCH_SIZE
        logger.info(
            f"Sinossi a blocchi: {len(input_summaries)} macro-capitoli → "
            f"{total_global_batches} riassunti parziali (batch da {GLOBAL_BATCH_SIZE})."
        )

        partial_summaries: list[str] = []
        for gi in range(0, len(input_summaries), GLOBAL_BATCH_SIZE):
            gbatch = input_summaries[gi:gi + GLOBAL_BATCH_SIZE]
            gpart  = gi // GLOBAL_BATCH_SIZE + 1

            if progress_cb:
                progress_cb(
                    total_sections + total_macros_est + gpart, total_steps,
                    f"Sinossi parziale {gpart}/{total_global_batches} "
                    f"(macro-capitoli {gi+1}–{gi+len(gbatch)})..."
                )

            partial = _strip_markdown(_call_ollama(
                _prompt_partial_global(
                    book_name, gbatch, gpart, total_global_batches,
                    global_section_start=gi + 1,
                    global_section_end=gi + len(gbatch),
                ),
                num_ctx=NUM_CTX_GLOBAL,
                num_predict=NUM_PREDICT_GLOBAL,
                temperature=0.05,
                timeout=600,
            ))
            if partial:
                partial_summaries.append(partial)
                logger.info(
                    f"Sinossi parziale {gpart}/{total_global_batches} completata "
                    f"({len(partial)} char)."
                )
            else:
                logger.warning(f"Sinossi parziale {gpart}/{total_global_batches} vuota.")

        global_summary = "\n\n".join(partial_summaries)

    logger.info(
        f"Sinossi globale finale: {len(global_summary)} char, "
        f"{len(global_summary.split())} parole."
    )

    # ── NER retention media sulle sezioni ──
    valid_results = [r for r in section_results if r is not None]
    retentions    = [r["ner_retention"]["retention_percent"] for r in valid_results
                     if r.get("ner_retention")]
    avg_retention = round(sum(retentions) / len(retentions), 1) if retentions else 0.0

    # ── NER retention GLOBALE sul global_summary ──
    all_entity_words: set[str] = set()
    for sec in sections:
        for c in sec.get("chunks", []):
            for e in c.get("entities", []):
                label = e.get("label") or e.get("entity_group", "")
                if label in ("PER", "LOC"):
                    word = e.get("word", "").replace("##", "").strip().lower()
                    if len(word) >= 3:
                        all_entity_words.add(word)
    global_summary_lower = (global_summary or "").lower()
    found_global         = {w for w in all_entity_words if w in global_summary_lower}
    global_ner_retention = {
        "total_unique_entities": len(all_entity_words),
        "found_in_global":       len(found_global),
        "retention_percent":     round(len(found_global) / len(all_entity_words) * 100, 1)
                                 if all_entity_words else 0.0,
    }
    logger.info(
        f"NER retention globale: {global_ner_retention['found_in_global']}/"
        f"{global_ner_retention['total_unique_entities']} entità "
        f"({global_ner_retention['retention_percent']}%)"
    )

    output = {
        "book_name":            book_name,
        "method":               method,
        "model":                settings.OLLAMA_MODEL,
        "created_at":           datetime.utcnow().isoformat(),
        "total_sections":       total_sections,
        "avg_ner_retention":    avg_retention,
        "global_ner_retention": global_ner_retention,
        "global_summary":       global_summary,
        "sections":             valid_results,
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if global_summary and progress_cb:
        progress_cb(total_steps, total_steps, "Completato!")

    return output
