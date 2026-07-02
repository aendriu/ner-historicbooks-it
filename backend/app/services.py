import os
import json
import shutil
import subprocess
import logging

from sqlalchemy.orm import Session
from app.config import BASE_DIR, DATA_DIR
from app.database import Book, BookStatus, Chapter, Summary
from app.ocr.llm_cleaner import run_llm_cleaner
from app.ner.ner_extractor import extract_ner_from_file
from app.semantic.chunker import run_semantic_chunker
from app.semantic.chapter_grouper import run_chapter_grouper
from app.semantic.summarizer import generate_chapter_summary

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

        cleaned_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}.json")
        llm_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}_llm.json")
        os.makedirs(os.path.dirname(cleaned_path), exist_ok=True)

        logger.info(f"[Book {book_id}] Fase 1: Pulizia OCR con LLM Ollama...")
        if not run_llm_cleaner(book.raw_file_path, llm_path, progress_cb=progress_cb):
            logger.warning(f"[Book {book_id}] LLM fallito, uso il file originale.")
            llm_path = book.raw_file_path

        logger.info(f"[Book {book_id}] Fase 1: Pulizia C post-LLM...")
        if not _run_c_cleaner(llm_path, cleaned_path, book_id):
            raise Exception("C-Cleaner fallito.")

        book.clean_file_path = cleaned_path
        db.commit()

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

        book.status = BookStatus.CHAPTER_GROUPING
        db.commit()

        logger.info(f"[Book {book_id}] Fase 3: Raggruppamento capitoli...")
        manifest_chapters = run_chapter_grouper(filename_no_ext, chunk_dir)
        book.chapter_manifest_path = manifest_chapters
        db.commit()

        # Salva capitoli nel DB
        with open(manifest_chapters, "r", encoding="utf-8") as f:
            chapter_manifest = json.load(f)

        cap_models = []
        for cap_data in chapter_manifest.get("chapters", []):
            ch = Chapter(
                book_id=book.id,
                chapter_id_num=cap_data["chapter_id"],
                title=cap_data["title"],
                char_start=cap_data["char_start"],
                char_end=cap_data["char_end"],
            )
            db.add(ch)
            cap_models.append((ch, cap_data))
        db.commit()

        # ── FASE 4: SUMMARIZATION ──
        book.status = BookStatus.SUMMARIZING
        db.commit()

        logger.info(f"[Book {book_id}] Fase 4: Generazione riassunti...")
        chapters_dir = os.path.join(DATA_DIR, "chapters", filename_no_ext)

        for chapter_model, cap_data in cap_models:
            chunks_data = []
            for cid in cap_data.get("chunk_ids", []):
                chunk_file = os.path.join(
                    chapters_dir, str(cap_data["chapter_id"]), f"chunk_{cid:03d}.json"
                )
                if os.path.exists(chunk_file):
                    with open(chunk_file, "r", encoding="utf-8") as f:
                        chunks_data.append(json.load(f))

            try:
                summary_text = generate_chapter_summary(cap_data["title"], chunks_data)
                if summary_text:
                    db.add(Summary(chapter_id=chapter_model.id, level=0, content=summary_text))
            except Exception as sum_err:
                logger.error(f"[Book {book_id}] Errore riassunto capitolo {cap_data.get('chapter_id')}: {sum_err}")
                continue  # non bloccare gli altri capitoli

        db.commit()

        # ── COMPLETATO ──
        book.status = BookStatus.COMPLETED
        db.commit()
        logger.info(f"[Book {book_id}] Pipeline completata con successo.")

    except Exception as e:
        logger.error(f"[Book {book_id}] Errore pipeline: {e}")
        book.status = BookStatus.ERROR
        db.commit()


def process_book_cleaning(book_id: int, db: Session, progress_cb=None):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return
    try:
        filename_no_ext = os.path.splitext(book.filename)[0]
        book.status = BookStatus.OCR_CLEANING
        db.commit()

        cleaned_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}.json")
        llm_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}_llm.json")
        os.makedirs(os.path.dirname(cleaned_path), exist_ok=True)

        logger.info(f"[Book {book_id}] Pulizia OCR con LLM Ollama...")
        if not run_llm_cleaner(book.raw_file_path, llm_path, progress_cb=progress_cb):
            logger.warning(f"[Book {book_id}] LLM fallito, uso il file originale.")
            llm_path = book.raw_file_path

        logger.info(f"[Book {book_id}] Pulizia C post-LLM...")
        if not _run_c_cleaner(llm_path, cleaned_path, book_id):
            raise Exception("C-Cleaner fallito.")

        book.clean_file_path = cleaned_path
        book.status = BookStatus.COMPLETED
        db.commit()
    except Exception as e:
        logger.error(f"[Book {book_id}] Errore pulizia: {e}")
        book.status = BookStatus.ERROR
        db.commit()
