import os
import json
import shutil
import subprocess
import logging

from sqlalchemy.orm import Session
from app.config import BASE_DIR, DATA_DIR
from app.database import Book, BookStatus, Chapter, Summary
from app.pipeline.ocr import run_llm_cleaner
from app.pipeline.ner import extract_ner_from_file
from app.pipeline.chunker import run_semantic_chunker
from app.pipeline.summarizer import run_hierarchical_summarization

logger = logging.getLogger(__name__)


def _run_c_cleaner(input_path: str, output_path: str, book_id: int) -> bool:
    """Esegue il binario C di pulizia su un singolo file, usando directory temporanee."""
    filename = os.path.basename(input_path)
    filename_no_ext = os.path.splitext(filename)[0]
    bin_path = os.path.abspath(os.path.join(BASE_DIR, "app", "ocr", "c_cleaner", "bin", "ocr_cleaner"))

    tmp_in = os.path.join(DATA_DIR, "cleaned", f"tmp_in_{book_id}")
    tmp_out = os.path.join(DATA_DIR, "cleaned", f"tmp_out_{book_id}")
    os.makedirs(tmp_in, exist_ok=True)
    os.makedirs(tmp_out, exist_ok=True)

    try:
        shutil.copy(input_path, os.path.join(tmp_in, f"{filename_no_ext}.json"))
        subprocess.run([bin_path, tmp_in, tmp_out], check=True)

        c_output = os.path.join(tmp_out, f"{filename_no_ext}-cleaned.json")
        if os.path.exists(c_output):
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            shutil.copy(c_output, output_path)
            return True
        return False
    finally:
        shutil.rmtree(tmp_in, ignore_errors=True)
        shutil.rmtree(tmp_out, ignore_errors=True)


def _run_ocr_phase(book: 'Book', db: Session, progress_cb=None, cancel_event=None) -> str:
    """Esegue la fase di pulizia OCR (LLM + C-Cleaner) su un libro.

    Args:
        book: istanza del libro da elaborare.
        db: sessione database attiva.
        progress_cb: callback opzionale per il progresso.
        cancel_event: evento opzionale per la cancellazione.

    Returns:
        Percorso del file pulito.

    Raises:
        Exception: se il C-Cleaner fallisce.
    """
    filename_no_ext = os.path.splitext(book.filename)[0]
    cleaned_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}.json")
    llm_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}_llm.json")
    os.makedirs(os.path.dirname(cleaned_path), exist_ok=True)

    logger.info(f"[Book {book.id}] Pulizia OCR con LLM Ollama...")
    if not run_llm_cleaner(book.raw_file_path, llm_path, progress_cb=progress_cb):
        logger.warning(f"[Book {book.id}] LLM fallito, uso il file originale.")
        llm_path = book.raw_file_path

    logger.info(f"[Book {book.id}] Pulizia C post-LLM...")
    if not _run_c_cleaner(llm_path, cleaned_path, book.id):
        raise Exception("C-Cleaner fallito.")

    book.clean_file_path = cleaned_path
    db.commit()
    return cleaned_path


def process_book_pipeline(book_id: int, db: Session, progress_cb=None):
    """Pipeline completa eseguita in background da FastAPI."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return

    try:
        filename_no_ext = os.path.splitext(book.filename)[0]

        # ── FASE 1: OCR CLEANING (LLM Ollama + C-Cleaner) ──
        book.status = BookStatus.OCR_CLEANING
        db.commit()
        _run_ocr_phase(book, db, progress_cb=progress_cb)

        # ── FASE 2: NER EXTRACTION ──
        book.status = BookStatus.NER_EXTRACTION
        db.commit()

        logger.info(f"[Book {book_id}] Fase 2: Estrazione NER...")
        ner_path = os.path.join(DATA_DIR, "ner", f"{filename_no_ext}_entities.json")
        if not extract_ner_from_file(cleaned_path, ner_path, progress_cb=progress_cb):
            raise Exception("NER fallito.")

        book.ner_file_path = ner_path
        db.commit()

        # ── FASE 3: SEMANTIC CHUNKING + CHAPTER GROUPING ──
        book.status = BookStatus.SEMANTIC_CHUNKING
        db.commit()

        logger.info(f"[Book {book_id}] Fase 3: Chunking semantico...")
        chunk_dir = os.path.join(DATA_DIR, "semantic", filename_no_ext)
        manifest_chunk = run_semantic_chunker(
            filename_no_ext, cleaned_path, ner_path,
            os.path.join(DATA_DIR, "semantic"), progress_cb=progress_cb
        )
        book.chunk_manifest_path = manifest_chunk
        db.commit()

        book.status = BookStatus.SUMMARIZING
        db.commit()

        logger.info(f"[Book {book_id}] Fase 4: Hierarchical Summarization (Livello 0)...")
        try:
            run_hierarchical_summarization(
                book_name=filename_no_ext,
                method="embed",
                semantic_dir=os.path.join(DATA_DIR, "semantic"),
                summaries_dir=os.path.join(DATA_DIR, "summaries"),
            )
        except Exception as sum_err:
            logger.error(f"[Book {book_id}] Errore summarization: {sum_err}")
            book.status = BookStatus.ERROR
            db.commit()
            return

        # ── COMPLETATO ──
        book.status = BookStatus.COMPLETED
        db.commit()
        logger.info(f"[Book {book_id}] Pipeline completata con successo.")


    except Exception as e:
        logger.error(f"[Book {book_id}] Errore pipeline: {e}")
        book.status = BookStatus.ERROR
        db.commit()


def process_book_cleaning(book_id: int, db: Session, progress_cb=None):
    """Esegue solo la fase di pulizia OCR per un libro."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return
    try:
        book.status = BookStatus.OCR_CLEANING
        db.commit()
        _run_ocr_phase(book, db, progress_cb=progress_cb)
        book.status = BookStatus.COMPLETED
        db.commit()
    except Exception as e:
        logger.error(f"[Book {book_id}] Errore pulizia: {e}")
        book.status = BookStatus.ERROR
        db.commit()

