"""
Pipeline execution endpoints.

Contains only pipeline-triggering POST endpoints and the progress GET.
Read-only data retrieval endpoints live in routers/data.py.
"""

from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends
from sqlalchemy.orm import Session
import os
import json
import logging

from app.database import SessionLocal, Book, BookStatus, Chapter, Summary
from app.config import DATA_DIR
from app.services import process_book_pipeline, process_book_cleaning
from app.ner.ner_extractor import extract_ner_from_file
from app.semantic.chunker import run_semantic_chunker
from app.semantic.chapter_grouper import run_chapter_grouper
from app.semantic.summarizer import generate_chapter_summary

logger = logging.getLogger("uvicorn.error")

NER_DIR = os.path.join(DATA_DIR, "ner")
SEMANTIC_DIR = os.path.join(DATA_DIR, "semantic")
CHAPTERS_DIR = os.path.join(DATA_DIR, "chapters")

router = APIRouter(tags=["pipeline"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_book_or_404(book_id: int, db: Session) -> Book:
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Libro non trovato")
    return book


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
    book = _get_book_or_404(book_id, db)
    book.status = BookStatus.UPLOADED

    def _do_all():
        progress_key = f"{book_id}_all"
        progress_store[progress_key] = {"status": "running", "logs": ["Avvio pipeline completa..."]}
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
    book = _get_book_or_404(book_id, db)
    book.status = BookStatus.OCR_CLEANING
    db.commit()

    def _do_clean():
        progress_key = f"{book_id}_clean"
        progress_store[progress_key] = {"status": "running", "logs": ["Avvio pulizia OCR..."]}
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
    book = _get_book_or_404(book_id, db)
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
def run_chunking(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Esegue solo il chunking semantico."""
    book = _get_book_or_404(book_id, db)
    if not book.clean_file_path or not os.path.exists(book.clean_file_path):
        raise HTTPException(400, "Testo pulito non disponibile.")
    if not book.ner_file_path or not os.path.exists(book.ner_file_path):
        raise HTTPException(400, "NER non disponibile. Esegui prima il NER.")

    def _do_chunking():
        progress_key = f"{book_id}_chunking"
        progress_store[progress_key] = {"status": "running", "logs": []}

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
                SEMANTIC_DIR, progress_cb=_cb,
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
    return {"message": "Chunking semantico avviato in background"}


@router.post("/api/books/{book_id}/run/chapters")
def run_chapters(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Esegue solo il raggruppamento capitoli."""
    book = _get_book_or_404(book_id, db)
    if not book.chunk_manifest_path or not os.path.exists(book.chunk_manifest_path):
        raise HTTPException(400, "Chunk manifest non disponibile. Esegui prima il chunking.")

    def _do_chapters():
        progress_key = f"{book_id}_chapters"
        progress_store[progress_key] = {"status": "running", "logs": []}

        def _cb(current, total, detail=""):
            progress_store[progress_key]["logs"].append(f"[{current}/{total}] {detail}")

        local_db = SessionLocal()
        try:
            local_book = local_db.query(Book).filter(Book.id == book_id).first()
            if not local_book:
                return

            local_book.status = BookStatus.CHAPTER_GROUPING
            local_db.commit()
            filename_no_ext = os.path.splitext(local_book.filename)[0]
            chunk_dir = os.path.dirname(local_book.chunk_manifest_path)
            manifest_path = run_chapter_grouper(filename_no_ext, chunk_dir, progress_cb=_cb)
            local_book.chapter_manifest_path = manifest_path

            # Salva capitoli nel DB
            with open(manifest_path, "r", encoding="utf-8") as f:
                ch_manifest = json.load(f)
            local_db.query(Chapter).filter(Chapter.book_id == local_book.id).delete()
            for cap in ch_manifest.get("chapters", []):
                local_db.add(Chapter(
                    book_id=local_book.id,
                    chapter_id_num=cap["chapter_id"],
                    title=cap["title"],
                    char_start=cap.get("char_start", 0),
                    char_end=cap.get("char_end", 0),
                ))
            local_book.status = BookStatus.COMPLETED
            progress_store[progress_key]["status"] = "completed"
            local_db.commit()
        except Exception as e:
            logger.error(f"Chapter grouping error: {e}")
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {e}")
        finally:
            local_db.close()

    background_tasks.add_task(_do_chapters)
    return {"message": "Chapter grouping avviato in background"}


@router.post("/api/books/{book_id}/run/summaries")
def run_summaries(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Genera i riassunti per tutti i capitoli del libro."""
    book = _get_book_or_404(book_id, db)
    chapters = db.query(Chapter).filter(Chapter.book_id == book_id).all()
    if not chapters:
        raise HTTPException(400, "Capitoli non disponibili. Esegui prima il chapter grouping.")

    def _do_summaries():
        progress_key = f"{book_id}_summaries"
        progress_store[progress_key] = {"status": "running", "logs": []}

        def _cb(current, total, detail=""):
            progress_store[progress_key]["logs"].append(f"Capitolo {current}/{total}: {detail}")

        local_db = SessionLocal()
        try:
            local_book = local_db.query(Book).filter(Book.id == book_id).first()
            if not local_book:
                return

            local_book.status = BookStatus.SUMMARIZING
            local_db.commit()
            filename_no_ext = os.path.splitext(local_book.filename)[0]
            chapters_dir = os.path.join(CHAPTERS_DIR, filename_no_ext)

            cap_models = local_db.query(Chapter).filter(
                Chapter.book_id == local_book.id
            ).order_by(Chapter.chapter_id_num).all()
            total_caps = len(cap_models)

            with open(local_book.chapter_manifest_path, "r", encoding="utf-8") as f:
                ch_manifest = json.load(f)
            cap_data_map = {c["chapter_id"]: c for c in ch_manifest.get("chapters", [])}

            for i, ch_model in enumerate(cap_models):
                cap_data = cap_data_map.get(ch_model.chapter_id_num)
                if not cap_data:
                    continue

                chunks_data = []
                for cid in cap_data.get("chunk_ids", []):
                    chunk_file = os.path.join(
                        chapters_dir, str(cap_data["chapter_id"]), f"chunk_{cid:03d}.json"
                    )
                    if os.path.exists(chunk_file):
                        with open(chunk_file, "r", encoding="utf-8") as f:
                            chunks_data.append(json.load(f))

                _cb(i + 1, total_caps, f"Generazione riassunto Capitolo {ch_model.chapter_id_num}")
                if summary_text := generate_chapter_summary(cap_data["title"], chunks_data):
                    local_db.query(Summary).filter(
                        Summary.chapter_id == ch_model.id, Summary.level == 0
                    ).delete()
                    local_db.add(Summary(chapter_id=ch_model.id, level=0, content=summary_text))

            local_book.status = BookStatus.COMPLETED
            progress_store[progress_key]["status"] = "completed"
            local_db.commit()
        except Exception as e:
            logger.error(f"Summarizing error: {e}")
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {e}")
        finally:
            local_db.close()

    background_tasks.add_task(_do_summaries)
    return {"message": "Generazione riassunti avviata in background"}
