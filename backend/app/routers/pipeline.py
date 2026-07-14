"""
Pipeline execution endpoints.

Contains only pipeline-triggering POST endpoints and the progress GET.
Read-only data retrieval endpoints live in routers/data.py.
"""

import glob
import math
import re
import threading as _threading

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
import os
import json
import logging
from typing import Literal

from app.database import SessionLocal, Book, BookStatus, Chapter, Summary
from app.config import DATA_DIR, settings
from app.dependencies import get_db, get_book_or_404
from app.services import process_book_pipeline, process_book_cleaning
from app.pipeline.ner import extract_ner_from_file
from app.pipeline.chunker import run_semantic_chunker, EMBED_SUBDIR, NER_SUBDIR
from app.pipeline.summarizer import run_hierarchical_summarization


class ChunkingRequest(BaseModel):
    method: Literal["embed", "ner"] = "embed"

logger = logging.getLogger("uvicorn.error")

NER_DIR      = os.path.join(DATA_DIR, "ner")
SEMANTIC_DIR  = os.path.join(DATA_DIR, "semantic")
SUMMARIES_DIR = os.path.join(DATA_DIR, "summaries")

# Stopwords italiane per il calcolo TF-IDF nel report di chunking
STOPWORDS = {
    "il","lo","la","i","gli","le","un","uno","una","di","a","da","in",
    "con","su","per","tra","fra","e","o","ma","se","che","non","si","è",
    "era","ai","del","dei","delle","della","degli","al","allo","alla","agli",
    "nel","nello","nella","nei","negli","nelle","col","coi","sui","come",
    "anche","già","più","suo","sua","suoi","sue","mio","mia","questo","quella",
    "essere","fare","avere","anche","così","poi","però","quando","dove","quello",
}


router = APIRouter(tags=["pipeline"])


# get_db e get_book_or_404 importati da app.dependencies


# ═══════════════════════════════════════════════════════════════════════════════
# PROGRESS TRACKING
# ═══════════════════════════════════════════════════════════════════════════════

# TODO: progress_store is an in-memory dict and has two known limitations:
#   1. It resets to empty on every server restart, losing all progress history.
#   2. It does NOT work correctly with multiple Uvicorn workers (each worker
#      has its own memory space, so a request landing on worker A cannot see
#      progress written by worker B).
# Replace with a shared backend such as Redis, a database table, or
# server-sent events (SSE) before deploying with multiple workers.
progress_store: dict = {}


@router.get("/api/books/{book_id}/progress/{phase}")
def get_progress(book_id: int, phase: str):
    key = f"{book_id}_{phase}"
    return progress_store.get(key, {"status": "idle", "logs": []})


# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/api/books/{book_id}/run/all")
def run_all(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Avvia la pipeline completa per un libro."""
    book = get_book_or_404(book_id, db)
    book.status = BookStatus.UPLOADED

    def _do_all():
        progress_key = f"{book_id}_all"
        progress_store[progress_key] = {"status": "running", "logs": [
            f"🤖 LLM: {settings.OLLAMA_HOST} | modello: {settings.OLLAMA_MODEL}",
            "Avvio pipeline completa..."
        ]}
        local_db = SessionLocal()

        def _cb(current, total, detail=""):
            progress_store[progress_key]["logs"].append(f"[{current}/{total}] {detail}")

        try:
            process_book_pipeline(book_id, local_db, progress_cb=_cb)
            updated_book = local_db.query(Book).filter(Book.id == book_id).first()
            if updated_book and updated_book.status == BookStatus.COMPLETED:
                progress_store[progress_key]["status"] = "completed"
                progress_store[progress_key]["logs"].append("Pipeline completata con successo.")
            else:
                progress_store[progress_key]["status"] = "error"
                progress_store[progress_key]["logs"].append("Pipeline fallita o terminata con errori.")
        except Exception as e:
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore imprevisto: {e}")
        finally:
            local_db.close()

    background_tasks.add_task(_do_all)
    return {"message": "Pipeline completa avviata in background"}


@router.post("/api/books/{book_id}/run/clean")
def run_clean(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Avvia solo la pulizia OCR per un libro."""
    book = get_book_or_404(book_id, db)
    book.status = BookStatus.OCR_CLEANING
    db.commit()

    def _do_clean():
        progress_key = f"{book_id}_clean"
        progress_store[progress_key] = {"status": "running", "logs": [
            f"🤖 LLM: {settings.OLLAMA_HOST} | modello: {settings.OLLAMA_MODEL}",
            "Avvio pulizia OCR..."
        ]}
        local_db = SessionLocal()

        def _cb(current, total, detail=""):
            progress_store[progress_key]["logs"].append(f"[{current}/{total}] {detail}")

        try:
            process_book_cleaning(book_id, local_db, progress_cb=_cb)
            updated_book = local_db.query(Book).filter(Book.id == book_id).first()
            if updated_book and updated_book.status == BookStatus.COMPLETED:
                progress_store[progress_key]["status"] = "completed"
                progress_store[progress_key]["logs"].append("Pulizia completata con successo.")
            else:
                progress_store[progress_key]["status"] = "error"
                progress_store[progress_key]["logs"].append("Pulizia fallita o terminata con errori.")
        except Exception as e:
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore imprevisto: {e}")
        finally:
            local_db.close()

    background_tasks.add_task(_do_clean)
    return {"message": "Pulizia OCR avviata in background"}


@router.post("/api/books/{book_id}/run/ner")
def run_ner(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Esegue solo l'estrazione NER."""
    book = get_book_or_404(book_id, db)
    if not book.clean_file_path or not os.path.exists(book.clean_file_path):
        raise HTTPException(400, "Testo pulito non disponibile. Esegui prima la pulizia OCR.")

    def _do_ner():
        progress_key = f"{book_id}_ner"
        progress_store[progress_key] = {"status": "running", "logs": []}

        def _cb(current, total, detail=""):
            msg = f"Chunk {current}/{total}"
            if isinstance(detail, int):
                msg += f" — {detail} entità trovate"
            elif detail:
                msg += f" — {detail}"
            progress_store[progress_key]["logs"].append(msg)

        local_db = SessionLocal()
        try:
            local_book = local_db.query(Book).filter(Book.id == book_id).first()
            if not local_book:
                return

            local_book.status = BookStatus.NER_EXTRACTION
            local_db.commit()
            filename_no_ext = os.path.splitext(local_book.filename)[0]
            ner_path = os.path.join(NER_DIR, f"{filename_no_ext}_entities.json")
            ok = extract_ner_from_file(local_book.clean_file_path, ner_path, progress_cb=_cb)
            if ok:
                local_book.ner_file_path = ner_path
                local_book.status = BookStatus.COMPLETED
                progress_store[progress_key]["status"] = "completed"
            else:
                local_book.status = BookStatus.ERROR
                progress_store[progress_key]["status"] = "error"
            local_db.commit()
        except Exception as e:
            logger.error(f"NER error: {e}")
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {e}")
        finally:
            local_db.close()

    background_tasks.add_task(_do_ner)
    return {"message": "NER avviato in background"}


@router.post("/api/books/{book_id}/run/chunking")
def run_chunking(book_id: int, body: ChunkingRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Esegue il chunking semantico con il metodo scelto (embed | ner)."""
    book = get_book_or_404(book_id, db)
    if not book.clean_file_path or not os.path.exists(book.clean_file_path):
        raise HTTPException(400, "Testo pulito non disponibile.")
    if not book.ner_file_path or not os.path.exists(book.ner_file_path):
        raise HTTPException(400, "NER non disponibile. Esegui prima il NER.")

    method = body.method

    def _do_chunking():
        progress_key = f"{book_id}_chunking"
        progress_store[progress_key] = {"status": "running", "logs": [f"Avvio chunking ({method.upper()} method)..."]}

        def _cb(current, total, detail=""):
            progress_store[progress_key]["logs"].append(f"[{current}/{total}] {detail}")

        local_db = SessionLocal()
        try:
            local_book = local_db.query(Book).filter(Book.id == book_id).first()
            if not local_book:
                return

            local_book.status = BookStatus.SEMANTIC_CHUNKING
            local_db.commit()
            filename_no_ext = os.path.splitext(local_book.filename)[0]
            manifest_path = run_semantic_chunker(
                filename_no_ext, local_book.clean_file_path, local_book.ner_file_path,
                SEMANTIC_DIR, progress_cb=_cb, method=method,
            )
            local_book.chunk_manifest_path = manifest_path
            local_book.status = BookStatus.COMPLETED
            progress_store[progress_key]["status"] = "completed"
            local_db.commit()
        except Exception as e:
            logger.error(f"Chunking error: {e}")
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {e}")
        finally:
            local_db.close()

    background_tasks.add_task(_do_chunking)
    return {"message": f"Chunking semantico ({method}) avviato in background"}


@router.get("/api/books/{book_id}/chunking-report")
def get_chunking_report(book_id: int, db: Session = Depends(get_db)):
    """Confronto scientifico tra i risultati dei due metodi di chunking (embed vs ner)."""
    book = get_book_or_404(book_id, db)
    filename_no_ext = os.path.splitext(book.filename)[0]

    embed_manifest_path = os.path.join(SEMANTIC_DIR, EMBED_SUBDIR, filename_no_ext, "manifest.json")
    ner_manifest_path   = os.path.join(SEMANTIC_DIR, NER_SUBDIR,   filename_no_ext, "manifest.json")

    embed_available = os.path.exists(embed_manifest_path)
    ner_available   = os.path.exists(ner_manifest_path)

    embed_manifest = None
    if embed_available:
        with open(embed_manifest_path, encoding="utf-8") as f:
            embed_manifest = json.load(f)
    ner_manifest = None
    if ner_available:
        with open(ner_manifest_path, encoding="utf-8") as f:
            ner_manifest = json.load(f)

    if not embed_available and not ner_available:
        raise HTTPException(404, "Nessun risultato di chunking disponibile per questo libro.")

    # STOPWORDS definite a livello di modulo

    def _tf(text: str) -> dict:
        """Frequenza termini normalizzata per lunghezza."""
        words = re.findall(r'\b[a-zA-ZÀ-ÿ]{3,}\b', text.lower())
        freq: dict = {}
        for w in words:
            if w not in STOPWORDS:
                freq[w] = freq.get(w, 0) + 1
        total = sum(freq.values()) or 1
        return {w: c / total for w, c in freq.items()}

    def _build_tfidf(tf_list: list[dict]) -> list[dict]:
        """Calcola TF-IDF da una lista di vettori TF.
        IDF = log(N / df) — penalizza parole che appaiono in molti chunk.
        """
        N = len(tf_list)
        df: dict = {}
        for tf in tf_list:
            for word in tf:
                df[word] = df.get(word, 0) + 1
        idf = {word: math.log(N / count) for word, count in df.items() if count < N}
        return [
            {w: v * idf[w] for w, v in tf.items() if w in idf}
            for tf in tf_list
        ]

    def _cosine(a: dict, b: dict) -> float:
        common = set(a) & set(b)
        if not common:
            return 0.0
        dot   = sum(a[w] * b[w] for w in common)
        mag_a = math.sqrt(sum(v**2 for v in a.values()))
        mag_b = math.sqrt(sum(v**2 for v in b.values()))
        return round(dot / (mag_a * mag_b), 4) if mag_a and mag_b else 0.0

    def _load_chunks_text(manifest_path: str) -> list[dict]:
        base = os.path.dirname(manifest_path)
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        chunks = []
        for c in manifest.get("chunks", []):
            chunk_file = os.path.join(base, f"chunk_{c['chunk_id']:03d}.json")
            text = ""
            if os.path.exists(chunk_file):
                try:
                    with open(chunk_file, encoding="utf-8") as f:
                        text = json.load(f).get("text", "")
                except Exception as e:
                    logger.warning(f"Errore lettura chunk: {e}")
            chunks.append({**c, "text": text})
        return chunks

    def _sec_num(hint: str) -> int:
        m = re.search(r'(\d+)', hint or "")
        return int(m.group(1)) if m else 0

    def _compute_similarity_profile(chunks: list[dict]) -> dict:
        """
        Calcola il profilo di coerenza usando TF-IDF cosine similarity:
        - intra: chunk consecutivi nella STESSA sezione semantica
        - boundary: chunk consecutivi su sezioni DIVERSE (i tagli semantici)
        - cross: coppie di chunk da sezioni lontane (distanza >= metà delle sezioni totali)
        """
        if len(chunks) < 3:
            return {"intra": [], "boundary": [], "cross": [],
                    "avg_intra": None, "avg_boundary": None, "avg_cross": None}

        # Costruisci TF-IDF su tutti i chunk
        tf_list  = [_tf(c.get("text", "")) for c in chunks]
        vecs     = _build_tfidf(tf_list)

        intra, boundary = [], []
        for i in range(len(chunks) - 1):
            s_i  = _sec_num(chunks[i].get("topic_hint", ""))
            s_i1 = _sec_num(chunks[i + 1].get("topic_hint", ""))
            sim  = _cosine(vecs[i], vecs[i + 1])
            entry = {
                "chunk_a": chunks[i]["chunk_id"],
                "chunk_b": chunks[i + 1]["chunk_id"],
                "topic_a": chunks[i].get("topic_hint", ""),
                "topic_b": chunks[i + 1].get("topic_hint", ""),
                "similarity": sim,
                "same_section": s_i == s_i1,
            }
            (intra if s_i == s_i1 else boundary).append(entry)

        # Cross: prendi UN rappresentante per ogni sezione, poi campiona coppie
        # a distanza >= max(3, total_sections // 3)
        section_rep: dict[int, int] = {}   # sec_num → indice chunk
        for idx, c in enumerate(chunks):
            s = _sec_num(c.get("topic_hint", ""))
            if s not in section_rep:
                section_rep[s] = idx

        sec_nums    = sorted(section_rep.keys())
        total_secs  = len(sec_nums)
        min_gap     = max(3, total_secs // 3)

        cross = []
        for idx_i, s_i in enumerate(sec_nums):
            for s_j in sec_nums[idx_i + 1:]:
                if s_j - s_i >= min_gap:
                    ci, cj = section_rep[s_i], section_rep[s_j]
                    cross.append({
                        "chunk_a":      chunks[ci]["chunk_id"],
                        "chunk_b":      chunks[cj]["chunk_id"],
                        "topic_a":      chunks[ci].get("topic_hint", ""),
                        "topic_b":      chunks[cj].get("topic_hint", ""),
                        "similarity":   _cosine(vecs[ci], vecs[cj]),
                        "same_section": False,
                    })
                    break   # una coppia per sezione sorgente
            if len(cross) >= 20:
                break

        def _avg(lst):
            return round(sum(x["similarity"] for x in lst) / len(lst), 4) if lst else None

        return {
            "intra":        intra[:30],
            "boundary":     boundary[:30],
            "cross":        cross,
            "avg_intra":    _avg(intra),
            "avg_boundary": _avg(boundary),
            "avg_cross":    _avg(cross),
            "n_intra":      len(intra),
            "n_boundary":   len(boundary),
            "n_cross":      len(cross),
        }

    # ── Boundary Agreement ──
    def extract_boundaries(chunks):
        """Estrae i confini di sezione Embed (da topic_hint)."""
        boundaries, last_section = [], None
        for c in chunks:
            m = re.search(r'(\d+)', c.get("topic_hint", ""))
            if m:
                sec_num = int(m.group(1))
                if sec_num != last_section:
                    boundaries.append({
                        "char":       c["char_start"],
                        "topic_hint": c["topic_hint"].replace(" (parte)", ""),
                        "chunk_id":   c["chunk_id"],
                    })
                    last_section = sec_num
        return boundaries

    def extract_ner_chapter_boundaries(ner_manifest):
        """Estrae i confini dei CAPITOLI NER L2 (da manifest['chapters'])."""
        chapters = ner_manifest.get("chapters", [])
        if chapters:
            # usa i capitoli L2 se disponibili
            return [{"char": ch["char_start"],
                     "topic_hint": ch["chapter_hint"],
                     "chunk_id": ch["chapter_id"]} for ch in chapters]
        # fallback: usa le sezioni L1
        return extract_boundaries(ner_manifest.get("chunks", []))

    comparison      = []
    avg_jaccard     = None
    embed_sec_count = 0
    ner_ch_count    = 0
    ner_sec_count   = 0
    tolerance       = 1500

    embed_profile = None
    ner_profile   = None

    if embed_available:
        try:
            embed_chunks_full = _load_chunks_text(embed_manifest_path)
            embed_profile     = _compute_similarity_profile(embed_chunks_full)
            embed_sec_count   = len(extract_boundaries(embed_manifest.get("chunks", [])))
        except Exception as e:
            logger.warning(f"Similarity embed fallita: {e}")
            embed_sec_count = len(extract_boundaries(embed_manifest.get("chunks", [])))

    if ner_available:
        try:
            ner_chunks_full = _load_chunks_text(ner_manifest_path)
            ner_profile     = _compute_similarity_profile(ner_chunks_full)
            ner_sec_count   = len(extract_boundaries(ner_manifest.get("chunks", [])))
            ner_ch_count    = len(ner_manifest.get("chapters", [])) or ner_sec_count
        except Exception as e:
            logger.warning(f"Similarity NER fallita: {e}")
            ner_sec_count = len(extract_boundaries(ner_manifest.get("chunks", [])))
            ner_ch_count  = len(ner_manifest.get("chapters", [])) or ner_sec_count

    if embed_available and ner_available:
        embed_b = extract_boundaries(embed_manifest.get("chunks", []))
        ner_b   = extract_ner_chapter_boundaries(ner_manifest)   # usa capitoli L2

        for eb in embed_b:
            if not ner_b:
                break
            closest_nb = min(ner_b, key=lambda nb: abs(nb["char"] - eb["char"]))
            dist  = abs(closest_nb["char"] - eb["char"])
            match = dist <= tolerance
            comparison.append({
                "embed_chunk_id":    eb["chunk_id"],
                "embed_topic":       eb["topic_hint"],
                "embed_char":        eb["char"],
                "best_ner_chunk_id": closest_nb["chunk_id"],
                "ner_char":          closest_nb["char"],
                "ner_topic":         closest_nb["topic_hint"],
                "dist_chars":        dist,
                "is_match":          match,
            })

        matches = sum(1 for r in comparison if r["is_match"])
        avg_jaccard = round(matches / embed_sec_count, 2) if embed_sec_count > 0 else 0.0

    return {
        "book_id":              book_id,
        "embed_available":      embed_available,
        "ner_available":        ner_available,
        "embed_total_chunks":   embed_manifest.get("total_chunks") if embed_available else None,
        "ner_total_chunks":     ner_manifest.get("total_chunks")   if ner_available   else None,
        "embed_total_sections": embed_sec_count if embed_available else None,
        "ner_total_sections":   ner_sec_count   if ner_available   else None,
        "avg_jaccard_score":    avg_jaccard,
        "comparison":           comparison,
        "tolerance_chars":      tolerance,
        "embed_similarity":     embed_profile,
        "ner_similarity":       ner_profile,
    }





# Lock globale: impedisce di avviare due summarizzazioni simultanee
_summarize_lock  = _threading.Lock()
_cancel_event    = _threading.Event()   # settato → il loop si ferma alla prossima sezione


@router.post("/api/run/summarize/cancel")
def cancel_summarize():
    """Ferma la summarizzazione in corso dopo la sezione corrente."""
    _cancel_event.set()
    return {"message": "Cancellazione richiesta — il processo si fermerà dopo la sezione corrente."}


@router.post("/api/books/{book_id}/run/summarize")
def run_summarize(
    book_id: int,
    body: ChunkingRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Avvia la Hierarchical Summarization (Livello 0) sui chunk semantici.
    method: embed | ner
    """
    book = get_book_or_404(book_id, db)
    method = body.method

    # Verifica che il chunking sia disponibile per il metodo scelto
    method_subdir = EMBED_SUBDIR if method == "embed" else NER_SUBDIR
    filename_no_ext = os.path.splitext(book.filename)[0]
    manifest_path = os.path.join(SEMANTIC_DIR, method_subdir, filename_no_ext, "manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(
            400,
            f"Chunking '{method}' non disponibile. Esegui prima il chunking semantico.",
        )

    if not _summarize_lock.acquire(blocking=False):
        raise HTTPException(
            409,
            "Una summarizzazione è già in corso. Attendi che finisca prima di rilanciare."
        )

    _cancel_event.clear()   # reset del flag prima di ogni nuova esecuzione

    def _do_summarize():
        try:
            progress_key = f"{book_id}_summarize_{method}"
            progress_store[progress_key] = {
                "status": "running",
                "logs": [
                    f"🤖 LLM: {settings.OLLAMA_HOST} | modello: {settings.OLLAMA_MODEL}",
                    f"Avvio Hierarchical Summarization ({method.upper()})...",
                ],
            }

            def _cb(current, total, detail=""):
                progress_store[progress_key]["logs"].append(f"[{current}/{total}] {detail}")

            local_db = SessionLocal()
            try:
                local_book = local_db.query(Book).filter(Book.id == book_id).first()
                if not local_book:
                    return
                local_book.status = BookStatus.SUMMARIZING
                local_db.commit()

                fn = os.path.splitext(local_book.filename)[0]
                run_hierarchical_summarization(
                    book_name=fn,
                    method=method,
                    semantic_dir=SEMANTIC_DIR,
                    summaries_dir=SUMMARIES_DIR,
                    progress_cb=_cb,
                    cancel_event=_cancel_event,
                )

                if _cancel_event.is_set():
                    local_book.status = BookStatus.COMPLETED
                    progress_store[progress_key]["status"] = "cancelled"
                    progress_store[progress_key]["logs"].append("⛔ Summarizzazione interrotta dall'utente. I riassunti parziali sono stati salvati.")
                else:
                    local_book.status = BookStatus.COMPLETED
                    progress_store[progress_key]["status"] = "completed"
                local_db.commit()
            except Exception as e:
                logger.error(f"Summarization error: {e}")
                progress_store[progress_key]["status"] = "error"
                progress_store[progress_key]["logs"].append(f"Errore: {e}")
            finally:
                local_db.close()
        finally:
            _summarize_lock.release()

    background_tasks.add_task(_do_summarize)
    return {"message": f"Hierarchical Summarization ({method}) avviata in background"}


@router.get("/api/books/{book_id}/summaries")
def get_summaries(book_id: int, method: str = "embed", model: str = None, db: Session = Depends(get_db)):
    """
    Restituisce i risultati della Hierarchical Summarization salvati su disco.
    method: embed | ner
    model:  nome modello (es. 'qwen3.5:2b'). Se omesso, restituisce il più recente.
    """
    _re = re  # alias locale per compatibilità

    book = get_book_or_404(book_id, db)
    method_subdir   = EMBED_SUBDIR if method == "embed" else NER_SUBDIR
    filename_no_ext = os.path.splitext(book.filename)[0]
    book_dir        = os.path.join(SUMMARIES_DIR, method_subdir, filename_no_ext)

    # ── Trova tutti i file summaries_*.json disponibili ──
    pattern = os.path.join(book_dir, "summaries_*.json")
    all_files = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)

    # Retrocompatibilità: considera anche il vecchio summaries.json senza modello
    legacy = os.path.join(book_dir, "summaries.json")
    if os.path.exists(legacy) and legacy not in all_files:
        all_files.append(legacy)

    if not all_files:
        raise HTTPException(
            404,
            "Riassunti non ancora generati. Usa POST /run/summarize prima.",
        )

    # Estrai i nomi dei modelli dai nomi file per il selettore nel frontend
    def _model_from_path(p: str) -> str:
        basename = os.path.basename(p)
        m = _re.match(r"summaries_(.+)\.json$", basename)
        return m.group(1).replace("_", ".") if m else "legacy"

    available_models = [_model_from_path(p) for p in all_files]

    # Seleziona il file richiesto (o il più recente)
    if model:
        safe = _re.sub(r"[^\w\-]", "_", model)
        target = os.path.join(book_dir, f"summaries_{safe}.json")
        if not os.path.exists(target):
            raise HTTPException(404, f"Nessun riassunto trovato per il modello '{model}'.")
        summaries_path = target
    else:
        summaries_path = all_files[0]   # il più recente

    with open(summaries_path, encoding="utf-8") as f:
        data = json.load(f)

    data["available_models"] = available_models
    data["current_model_file"] = os.path.basename(summaries_path)
    return data
