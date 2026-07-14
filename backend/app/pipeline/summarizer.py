"""
Hierarchical Summarization — Livello 0
Strategia a piramide adattiva per Qwen 2.5 3B (via Ollama).

Flusso per ogni sezione semantica:
  1. Se il testo totale della sezione <= MAX_CHARS_PER_CALL:
       → 1 sola chiamata Ollama  (caso comune con sezioni brevi)
  2. Altrimenti batch adattivo:
       → Dividi i chunk in gruppi da MAX_CHARS_PER_CALL
       → Genera sub-riassunti (L1)
       → Unisci sub-riassunti in 1 riassunto di sezione (L2)

Flusso per il libro:
  - Raccogli tutti i riassunti di sezione
  - Se il totale <= MAX_CHARS_PER_CALL → 1 sola chiamata
  - Altrimenti batch dei riassunti → 1 merge finale (Livello 0)

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

# ─── Costanti (bilancio qualità / VRAM per GPU da 16GB con 2 worker paralleli) ─
MAX_CHARS_PER_CALL = 20_000   # input per sezione
NUM_CTX            = 8_192    # contesto per riassunti di sezione
NUM_CTX_GLOBAL     = 32_768   # contesto per sinossi Livello 0 (tutti i riassunti in una call)

# ─── Ollama helper ────────────────────────────────────────────────────────────

def _strip_thinking(text: str) -> str:
    """Rimuove i blocchi <think>...</think> generati da modelli Qwen3 in thinking mode."""
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


def _call_ollama(prompt: str, timeout: int = 480) -> str:
    """Singola chiamata all'API Ollama con streaming. Retry automatico se risposta vuota."""
    host = settings.OLLAMA_HOST.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}:{settings.OLLAMA_PORT}"
    url = f"{host}/api/generate"

    def _do_call(p: str) -> str:
        try:
            r = requests.post(
                url,
                json={
                    "model":   settings.OLLAMA_MODEL,
                    "prompt":  p,
                    "stream":  True,
                    "think":   False,   # top-level: disabilita thinking Qwen3 (dentro options viene ignorato)
                    "options": {
                        "temperature": 0.1,
                        "num_ctx":     NUM_CTX,
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
            raw = "".join(parts)
            result = _strip_thinking(raw)
            if not result:
                # Log dei primi 300 char grezzi per capire cosa restituisce Ollama
                preview = raw[:300].replace("\n", "↵") if raw else "<STRINGA VUOTA>"
                logger.warning(f"Risposta vuota dopo strip. Raw preview: {preview}")
            return result
        except Exception as e:
            logger.error(f"Errore chiamata Ollama: {e}")
            return ""

    # Chiamata unica: think:False nelle options è sufficiente per disabilitare il thinking Qwen3
    return _do_call(prompt)


def _call_ollama_long(prompt: str, timeout: int = 600) -> str:
    """Come _call_ollama ma con contesto e output estesi per il Livello 0.
    Usa OLLAMA_MODEL_GLOBAL se configurato, altrimenti cade su OLLAMA_MODEL."""
    host = settings.OLLAMA_HOST.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}:{settings.OLLAMA_PORT}"
    url = f"{host}/api/generate"

    # Modello per Livello 0: usa model_global se definito, altrimenti model standard
    model_global = getattr(settings, "OLLAMA_MODEL_GLOBAL", "").strip()
    model = model_global if model_global else settings.OLLAMA_MODEL

    try:
        r = requests.post(
            url,
            json={
                "model":   model,
                "prompt":  prompt,
                "stream":  True,
                "think":   False,
                "options": {
                    "temperature": 0.2,
                    "num_ctx":     NUM_CTX_GLOBAL,
                    "num_predict": 8192,   # ~6000 parole max output
                },
            },
            stream=True,
            timeout=timeout,
        )
        r.raise_for_status()
        full_response = []
        for line in r.iter_lines():
            if not line:
                continue
            try:
                chunk = json.loads(line)
                full_response.append(chunk.get("response", ""))
                if chunk.get("done", False):
                    break
            except json.JSONDecodeError:
                continue
        return _strip_thinking("".join(full_response))
    except Exception as e:
        logger.error(f"Errore chiamata Ollama (long): {e}")
        return ""


# _call_llm / _call_llm_long → alias diretti su Ollama (Claude solo per testing separato)
_call_llm      = _call_ollama
_call_llm_long = _call_ollama_long


# ─── Prompt builder ───────────────────────────────────────────────────────────

def _prompt_section_batch(text: str, entities_str: str) -> str:
    """Costruisce il prompt per il riassunto di un batch di testo con entità."""
    return f"""Sei un assistente editoriale esperto in letteratura italiana storica.
Scrivi un riassunto dettagliato e fedele di questo frammento di testo.

Personaggi e luoghi presenti nel testo: {entities_str}

REGOLE:
- Descrivi gli eventi principali nell'ordine in cui avvengono.
- Menziona i personaggi e luoghi solo se effettivamente presenti nel testo.
- Non inventare eventi non presenti nel testo.
- Lunghezza proporzionale al testo: se il testo è breve, il riassunto può essere breve.
- Rispondi SOLO con il testo del riassunto, senza preamboli o titoli.

TESTO:
{text}
"""

def _prompt_merge_summaries(summaries: list[str], title: str) -> str:
    """Costruisce il prompt per unificare riassunti parziali di una sezione."""
    joined = "\n\n".join(f"Parte {i+1}:\n{s}" for i, s in enumerate(summaries))
    return f"""Sei un assistente editoriale esperto in letteratura italiana storica.
Unifica i seguenti riassunti parziali della sezione "{title}" in un unico testo coeso e completo.

REGOLE:
- Mantieni TUTTI i nomi di personaggi e luoghi.
- Mantieni TUTTI gli eventi descritti, nell'ordine narrativo corretto.
- Elimina solo le ripetizioni letterali.
- Il risultato deve essere lungo e dettagliato quanto la somma delle parti.
- Rispondi SOLO con il testo unificato, senza preamboli o titoli.

RIASSUNTI PARZIALI:
{joined}
"""

def _prompt_section_title(summary: str) -> str:
    """Costruisce il prompt per generare un titolo breve per una sezione."""
    return f"""Sei un assistente editoriale esperto in letteratura italiana storica.
Dai un titolo breve (massimo 6 parole) a questa sezione narrativa, come se fosse
il titolo di un capitolo. Il titolo deve catturare il momento o l'evento principale.

Rispondi SOLO con il titolo, senza virgolette, senza preamboli, senza punto finale.

RIASSUNTO DELLA SEZIONE:
{summary[:800]}
"""

def _prompt_global_summary(book_name: str, chapter_summaries: list[str]) -> str:
    """Costruisce il prompt per il riassunto globale (Livello 0) dell'intera opera."""
    # Pulisce il nome del libro: rimuove hash iniziale, estensione, underscores
    clean_name = re.sub(r'^[0-9a-f]{6,}_', '', book_name)   # rimuove hash tipo "45e11373_"
    clean_name = clean_name.replace('_', ' ').replace('.txt', '').replace('.json', '').strip().title()
    joined = "\n\n".join(f"--- Sezione {i+1} ---\n{s}" for i, s in enumerate(chapter_summaries))
    return f"""Sei un critico letterario esperto in letteratura italiana.
Scrivi il RIASSUNTO COMPLETO E DETTAGLIATO (Livello 0) dell'opera "{clean_name}".

Questo è il riassunto di livello più alto: deve coprire l'INTERA opera dall'inizio alla fine,
includendo tutti i personaggi principali, i luoghi, gli eventi e gli sviluppi narrativi.

REGOLE:
- Scrivi ALMENO 2000-2500 parole: questo è il riassunto dell'intera opera, deve essere esaustivo.
- Segui l'ordine narrativo cronologico dell'opera.
- Cita esplicitamente i personaggi principali e i luoghi.
- Non omettere nessuna sezione importante della trama.
- Non usare elenchi puntati: scrivi in forma di prosa continua e fluida.
- Rispondi SOLO con il testo del riassunto, senza preamboli, senza titoli.

RIASSUNTI DELLE SEZIONI:
{joined}
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
            "retention_percent":   100.0,
            "total_key_entities":  0,
            "survived":            [],
            "lost":                [],
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

# ─── Summarizer per una singola sezione ──────────────────────────────────────

def _summarize_section(chunks: list[dict]) -> str:
    """Genera il riassunto di una sezione semantica.

    Adatta automaticamente il numero di chiamate Ollama alla lunghezza del testo.
    """
    if not chunks:
        return ""

    # Raccoglie testo e entità di tutta la sezione
    full_text = "\n\n".join(c.get("text", "") for c in chunks)
    all_entities: set[str] = set()
    for c in chunks:
        for e in c.get("entities", []):
            label = e.get("label") or e.get("entity_group", "")
            if label in ("PER", "LOC"):
                w = e.get("word", "").replace("##", "").strip()
                if len(w) >= 3:
                    all_entities.add(w)
    entities_str = ", ".join(sorted(all_entities)) or "Nessuna entità specifica"

    # ── Caso semplice: testo breve → 1 sola chiamata ──
    if len(full_text) <= MAX_CHARS_PER_CALL:
        logger.info(f"  → Invio sezione a Ollama: {len(full_text)} char")
        return _call_llm(_prompt_section_batch(full_text, entities_str))

    # ── Caso piramide: testo lungo → batch → merge ──
    # Costruisce batch di chunk senza superare MAX_CHARS_PER_CALL
    batches: list[list[dict]] = []
    current_batch: list[dict] = []
    current_chars  = 0

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

    # L1: sub-riassunti per ogni batch
    sub_summaries: list[str] = []
    for batch in batches:
        batch_text     = "\n\n".join(c.get("text", "") for c in batch)
        batch_entities: set[str] = set()
        for c in batch:
            for e in c.get("entities", []):
                label = e.get("label") or e.get("entity_group", "")
                if label in ("PER", "LOC"):
                    w = e.get("word", "").replace("##", "").strip()
                    if len(w) >= 3:
                        batch_entities.add(w)
        e_str  = ", ".join(sorted(batch_entities)) or "Nessuna entità specifica"
        sub    = _call_llm(_prompt_section_batch(batch_text, e_str))
        if sub:
            sub_summaries.append(sub)

    if not sub_summaries:
        return ""

    if len(sub_summaries) == 1:
        return sub_summaries[0]

    # L2: merge dei sub-riassunti
    title  = chunks[0].get("topic_hint", "Sezione").replace(" (parte)", "")
    merged = _call_llm(_prompt_merge_summaries(sub_summaries, title))
    return merged or " ".join(sub_summaries)

# ─── Entry point principale ───────────────────────────────────────────────────

def run_hierarchical_summarization(
    book_name:    str,
    method:       str,
    semantic_dir: str,
    summaries_dir: str,
    progress_cb:  Callable | None = None,
    cancel_event=None,   # threading.Event — se settato il loop si ferma
) -> dict:
    """
    Esegue il processo completo di Hierarchical Summarization (Livello 0).

    Input:  {semantic_dir}/{method}_method/{book_name}/  (chunk JSON)
    Output: {summaries_dir}/{method}_method/{book_name}/summaries.json
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
    if progress_cb:
        progress_cb(0, total_sections, f"Trovate {total_sections} sezioni semantiche.")

    # ── Percorso di output (nome file include il modello, per confronto tra LLM) ──
    # Es: summaries_qwen3.5_2b.json, summaries_llama3.2_3b.json
    _safe_model = re.sub(r"[^\w\-]", "_", settings.OLLAMA_MODEL)   # qwen3.5:2b → qwen3_5_2b
    out_dir   = os.path.join(summaries_dir, method_subdir, book_name)
    os.makedirs(out_dir, exist_ok=True)
    out_path  = os.path.join(out_dir, f"summaries_{_safe_model}.json")

    # ── Resume: carica riassunti già completati (solo quelli con summary non vuota) ──
    section_results: list[dict] = [None] * total_sections
    if os.path.exists(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                existing = json.load(f)
            for r in existing.get("sections", []):
                idx_r = r.get("section_idx", 0) - 1
                # Carica solo se il riassunto è non vuoto — sezioni vuote vengono riprovate
                if 0 <= idx_r < total_sections and r.get("summary", "").strip():
                    section_results[idx_r] = r
            already_done = sum(1 for r in section_results if r is not None)
            if already_done > 0:
                logger.info(f"Resume: trovate {already_done}/{total_sections} sezioni già completate — le salto.")
                if progress_cb:
                    progress_cb(already_done, total_sections, f"Resume: {already_done}/{total_sections} sezioni già completate.")
        except Exception as e:
            logger.warning(f"Impossibile caricare riassunti parziali esistenti: {e}")

    def _save_partial():
        """Salva il file summaries.json con i risultati parziali finora completati."""
        valid_so_far = [r for r in section_results if r is not None]
        retentions   = [r["ner_retention"]["retention_percent"] for r in valid_so_far]
        partial_output = {
            "book_name":         book_name,
            "method":            method,
            "model":             settings.OLLAMA_MODEL,
            "created_at":        datetime.utcnow().isoformat(),
            "total_sections":    total_sections,
            "completed_sections": len(valid_so_far),
            "avg_ner_retention": round(sum(retentions) / len(retentions), 1) if retentions else 0.0,
            "global_summary":    "",   # verrà popolato solo alla fine
            "sections":          valid_so_far,
        }
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(partial_output, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Errore salvataggio parziale: {e}")

    # ── Esecuzione sequenziale garantita (no ThreadPool: Ollama è single-thread sulla GPU) ──
    for idx, sec in enumerate(sections):
        # Stop se l'utente ha richiesto la cancellazione
        if cancel_event is not None and cancel_event.is_set():
            logger.info(f"Cancellazione richiesta: fermo dopo la sezione {idx} ({idx}/{total_sections} completate).")
            break

        # Resume: salta le sezioni già completate
        if section_results[idx] is not None:
            if progress_cb:
                progress_cb(idx + 1, total_sections, f"[già fatto] Sezione {idx+1}/{total_sections}: {sec['topic']}")
            continue

        topic  = sec["topic"]
        chunks = sec["chunks"]

        if progress_cb:
            progress_cb(idx + 1, total_sections, f"Sezione {idx+1}/{total_sections}: {topic}")

        try:
            summary = _summarize_section(chunks)

            if not summary:
                logger.warning(f"Sezione {idx+1} ({topic}) — riassunto vuoto dopo retry.")

            all_ents = [e for c in chunks for e in c.get("entities", [])]
            ner      = _calculate_ner_retention(all_ents, summary)

            result = {
                "section_idx":   idx + 1,
                "topic_hint":    topic,
                "topic_generic": topic,
                "num_chunks":    len(chunks),
                "total_chars":   sum(len(c.get("text", "")) for c in chunks),
                "summary":       summary,
                "ner_retention": ner,
            }
            section_results[idx] = result
            _save_partial()

            logger.info(
                f"Sezione {idx+1}/{total_sections} salvata — "
                f"NER retention: {ner['retention_percent']}% "
                f"(lost: {ner['lost']})"
            )
        except Exception as e:
            logger.error(f"Sezione {idx+1} — errore non gestito: {e}")


    # ── Livello 0: riassunto globale del libro ──
    if progress_cb:
        progress_cb(total_sections, total_sections, "Generazione Livello 0 (sinossi globale)...")

    chapter_summaries = [r["summary"] for r in section_results if r is not None and r.get("summary")]

    # NUM_CTX_GLOBAL = 32768 token. Riserviamo 4096 token per l'output.
    # ~28000 token disponibili per input → ~100.000 char (stima: 1 token ≈ 3.5 char)
    MAX_GLOBAL_CHARS = (NUM_CTX_GLOBAL - 4096) * 3
    combined_len = sum(len(s) for s in chapter_summaries)

    if combined_len <= MAX_GLOBAL_CHARS:
        global_summary = _call_llm_long(_prompt_global_summary(book_name, chapter_summaries))
    else:
        # Batch: finestre di riassunti → sub-globali → merge finale
        batch_size = max(1, MAX_GLOBAL_CHARS // max(1, combined_len // len(chapter_summaries)))
        sub_globals: list[str] = []
        for i in range(0, len(chapter_summaries), batch_size):
            batch = chapter_summaries[i:i + batch_size]
            sub   = _call_llm_long(_prompt_global_summary(book_name, batch))
            if sub:
                sub_globals.append(sub)
        if len(sub_globals) == 1:
            global_summary = sub_globals[0]
        else:
            global_summary = _call_llm_long(
                _prompt_merge_summaries(sub_globals, f"Sinossi completa di {book_name}")
            )

    # ── Calcolo NER retention media (filtra sezioni fallite) ──
    valid_results = [r for r in section_results if r is not None]
    retentions = [r["ner_retention"]["retention_percent"] for r in valid_results
                  if r.get("ner_retention")]
    avg_retention = round(sum(retentions) / len(retentions), 1) if retentions else 0.0

    # ── Calcolo NER retention GLOBALE sul global_summary ──
    # Raccoglie tutte le entità uniche PER/LOC dell'intero libro direttamente dai chunks originali
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
    found_global = {w for w in all_entity_words if w in global_summary_lower}
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

    # Modello usato per Livello 0
    model_global_used = getattr(settings, "OLLAMA_MODEL_GLOBAL", "").strip() or settings.OLLAMA_MODEL

    output = {
        "book_name":            book_name,
        "method":               method,
        "model":                model_global_used,  # <-- mostra nel frontend il modello usato per L0
        "model_l2":             settings.OLLAMA_MODEL,
        "created_at":           datetime.utcnow().isoformat(),
        "total_sections":       total_sections,
        "avg_ner_retention":    avg_retention,
        "global_ner_retention": global_ner_retention,
        "global_summary":       global_summary,
        "sections":             valid_results,
    }

    # Salva il file finale con global_summary
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if progress_cb:
        progress_cb(total_sections, total_sections, "✅ Completato.")

    return output
