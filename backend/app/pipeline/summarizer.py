"""
Hierarchical Summarization — Map-Reduce Gerarchico
Strategia a piramide adattiva per SLM locali (via Ollama).

Architettura a 3 fasi:

  Fase 1 — Riassunti delle Sezioni Semantiche (Livello 0):
    Per ogni sezione semantica (= capitolo), genera un resoconto
    esaustivo e dettagliato. Se la sezione è troppo lunga, la divide
    in batch, genera sub-resoconti, e li fonde in un unico testo.

  Fase 2 — Macro-Capitoli (solo per libri lunghi, >MACRO_THRESHOLD capitoli):
    Raggruppa i resoconti delle sezioni in blocchi di MACRO_BATCH_SIZE
    (es. 6) e genera un riassunto intermedio per ogni blocco.
    Questo evita di sovraccaricare l'LLM con decine di resoconti
    nella fase finale, preservando dettagli e personaggi secondari.

  Fase 3 — Sinossi Globale:
    Prende i macro-riassunti (o i resoconti diretti se il libro è
    breve) e genera la sinossi finale dell'intera opera.

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
NUM_PREDICT_SECTION =  6_144  # output esplicito: nessun troncamento prematuro

# Lv 1/2 — macro-capitoli e sinossi globale
NUM_CTX_GLOBAL     = 32_768
NUM_PREDICT_GLOBAL =  8_192

# Map-Reduce: soglia e dimensione dei macro-capitoli
MACRO_THRESHOLD  = 10   # numero minimo di sezioni per attivare la fase intermedia
MACRO_BATCH_SIZE =  6   # quante sezioni raggruppare in un macro-capitolo

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


# ─── Prompt builder ───────────────────────────────────────────────────────────

def _prompt_section_batch(text: str, entities_str: str) -> str:
    """Prompt per il resoconto esaustivo di un frammento di testo (Livello 0).

    Obiettivo: massima verbosità e fedeltà informativa. Il modello deve
    documentare minuziosamente ogni evento, dialogo e sfumatura presente
    nel testo, senza omettere nulla di significativo.
    """
    return f"""Sei un analista letterario esperto in letteratura italiana storica.
Produci un resoconto estremamente dettagliato, discorsivo ed esaustivo di questo frammento di testo.

Personaggi e luoghi presenti nel testo: {entities_str}

REGOLE:
- Il tuo obiettivo primario è preservare l'intera ricchezza informativa del testo originale. Non omettere nulla.
- Documenta ogni evento nell'ordine in cui avviene, con tutti i dettagli narrativi e descrittivi.
- Per ogni personaggio presente, descrivi con precisione le sue azioni, le sue parole, i suoi pensieri e il suo stato d'animo.
- Per ogni luogo citato, descrivi il contesto ambientale e gli eventi che vi si svolgono.
- Includi ogni dialogo rilevante, ogni scambio di battute, ogni reazione emotiva dei personaggi.
- Descrivi anche gli elementi secondari, i dettagli di colore, le atmosfere e le situazioni di contorno.
- Non inventare eventi o dettagli non presenti nel testo.
- Scrivi in prosa continua e fluida, organizzata in paragrafi. Non usare elenchi puntati, titoli o simboli markdown.
- Rispondi SOLO con il testo del resoconto, senza preamboli, senza titoli, senza note finali.

TESTO:
{text}
"""


def _prompt_merge_summaries(summaries: list[str], title: str) -> str:
    """Prompt per unificare resoconti parziali di una sezione."""
    joined = "\n\n".join(f"Parte {i+1}:\n{s}" for i, s in enumerate(summaries))
    return f"""Sei un assistente editoriale esperto in letteratura italiana storica.
Unifica i seguenti resoconti parziali della sezione "{title}" in un unico testo coeso e completo.

REGOLE:
- Mantieni TUTTI i nomi di personaggi e luoghi.
- Mantieni TUTTI gli eventi descritti, nell'ordine narrativo corretto.
- Elimina solo le ripetizioni letterali.
- Il risultato deve essere lungo e dettagliato quanto la somma delle parti.
- Rispondi SOLO con il testo unificato, senza preamboli o titoli.

RESOCONTI PARZIALI:
{joined}
"""


def _clean_book_name(book_name: str) -> str:
    """Pulisce il nome del libro: rimuove hash iniziale, estensione, underscores."""
    clean = re.sub(r'^[0-9a-f]{6,}_', '', book_name)
    return clean.replace('_', ' ').replace('.txt', '').replace('.json', '').strip().title()


def _prompt_global_summary(book_name: str, chapter_summaries: list[str]) -> str:
    """Prompt per la sinossi globale dell'intera opera.

    Riceve i riassunti dei macro-capitoli (o delle sezioni dirette se il libro
    è breve) e chiede all'LLM di produrre una panoramica fedele e narrativa.
    """
    clean_name = _clean_book_name(book_name)
    joined = "\n\n".join(f"--- Sezione {i+1} ---\n{s}" for i, s in enumerate(chapter_summaries))
    return f"""Sei un critico letterario esperto in letteratura italiana.
Scrivi il RIASSUNTO NARRATIVO COMPLETO dell'opera "{clean_name}".

REGOLA FONDAMENTALE — ANTI-ALLUCINAZIONE:
- Scrivi SOLO eventi, personaggi e luoghi che compaiono esplicitamente nei
  riassunti forniti qui sotto. Non inventare nulla.
- Se un evento non è menzionato nei riassunti, NON includerlo.

FORMATO:
- Scrivi SOLO in prosa continua, organizzata in paragrafi.
- NON usare titoli, intestazioni, elenchi puntati o numerati.
- NON usare asterischi, trattini o simboli markdown.
- Segui l'ordine narrativo cronologico.
- Rispondi SOLO con il testo del riassunto, senza preamboli.

RIASSUNTI DELLE SEZIONI (questa è l'unica fonte da cui puoi attingere):
{joined}
"""


def _prompt_macro_chapter(book_name: str, chapter_summaries: list[str],
                           part_num: int, total_parts: int) -> str:
    """Prompt per il riassunto di un macro-capitolo.

    Un macro-capitolo è un gruppo di sezioni consecutive (es. le sezioni 7-12).
    L'LLM deve fondere i resoconti delle singole sezioni in un unico testo
    coerente, senza perdere personaggi o eventi secondari.

    Args:
        book_name:         nome grezzo del libro (con hash).
        chapter_summaries: lista dei resoconti delle sezioni in questo gruppo.
        part_num:          numero progressivo del macro-capitolo (1-based).
        total_parts:       numero totale di macro-capitoli.
    """
    clean_name = _clean_book_name(book_name)
    joined = "\n\n".join(f"--- Sezione {i+1} ---\n{s}" for i, s in enumerate(chapter_summaries))
    return f"""Sei un critico letterario esperto in letteratura italiana.
Scrivi il riassunto dettagliato della PARTE {part_num} di {total_parts} dell'opera "{clean_name}".

Questa parte comprende {len(chapter_summaries)} sezioni consecutive del libro.

REGOLE:
- Mantieni TUTTI i personaggi citati nelle sezioni, inclusi quelli secondari.
- Mantieni TUTTI i luoghi e gli eventi nell'ordine narrativo corretto.
- Scrivi in prosa continua e fluida, senza elenchi puntati, senza titoli, senza headers.
- NON usare asterischi, trattini o simboli per creare liste.
- Il riassunto deve essere lungo e dettagliato: non omettere nulla di significativo.
- Rispondi SOLO con il testo del riassunto, senza preamboli o titoli.

RESOCONTI DELLE SEZIONI:
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
        return _call_ollama(_prompt_section_batch(full_text, entities_str))

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
        sub   = _call_ollama(_prompt_section_batch(batch_text, e_str))
        if sub:
            sub_summaries.append(sub)

    if not sub_summaries:
        return ""
    if len(sub_summaries) == 1:
        return sub_summaries[0]

    # L2: merge dei sub-resoconti
    title  = chunks[0].get("topic_hint", "Sezione").replace(" (parte)", "")
    merged = _call_ollama(_prompt_merge_summaries(sub_summaries, title))
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
    if progress_cb:
        progress_cb(0, total_sections, f"Trovate {total_sections} sezioni semantiche.")

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
                    progress_cb(already_done, total_sections,
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
                progress_cb(idx + 1, total_sections,
                            f"[già fatto] Sezione {idx+1}/{total_sections}: {sec['topic']}")
            continue

        topic  = sec["topic"]
        chunks = sec["chunks"]

        if progress_cb:
            progress_cb(idx + 1, total_sections, f"Sezione {idx+1}/{total_sections}: {topic}")

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
        progress_cb(total_sections, total_sections, "Generazione Sinossi Globale...")

    chapter_summaries = [
        r["summary"] for r in section_results
        if r is not None and r.get("summary")
    ]

    if len(chapter_summaries) <= MACRO_THRESHOLD:
        logger.info(f"Libro breve ({len(chapter_summaries)} sezioni ≤ {MACRO_THRESHOLD}): sinossi diretta.")
        if progress_cb:
            progress_cb(total_sections, total_sections,
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
                progress_cb(total_sections, total_sections,
                            f"Macro-capitolo {part_num}/{total_macros} "
                            f"(sezioni {i+1}–{i+len(batch)})...")

            macro = _call_ollama(
                _prompt_macro_chapter(book_name, batch, part_num, total_macros),
                num_ctx=NUM_CTX_GLOBAL,
                num_predict=NUM_PREDICT_GLOBAL,
                temperature=0.2,
                timeout=600,
            )
            if macro:
                macro_summaries.append(macro)
                logger.info(f"Macro-capitolo {part_num}/{total_macros} completato ({len(macro)} char).")
            else:
                logger.warning(f"Macro-capitolo {part_num}/{total_macros} vuoto.")

        input_summaries = macro_summaries

    global_summary = _call_ollama(
        _prompt_global_summary(book_name, input_summaries),
        num_ctx=NUM_CTX_GLOBAL,
        num_predict=NUM_PREDICT_GLOBAL,
        temperature=0.2,
        timeout=600,
    )
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

    if progress_cb:
        progress_cb(total_sections, total_sections, "✅ Completato.")

    return output
