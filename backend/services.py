import os
import sys
import subprocess
import json
import logging

# Aggiungiamo backend al sys.path per importare correttamente
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ner.ner_extractor import extract_ner_from_file
from semantic.chunker import run_semantic_chunker
from semantic.chapter_grouper import run_chapter_grouper
from semantic.summarizer import generate_chapter_summary
from ocr.llm_cleaner import run_llm_cleaner
from sqlalchemy.orm import Session
from database import Book, BookStatus

logger = logging.getLogger(__name__)

# Directory Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

def process_book_pipeline(book_id: int, db: Session):
    """
    Pipeline completa eseguita in background da FastAPI.
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        return

    try:
        # ==========================================
        # FASE 1: OCR CLEANING (LLM Bedrock)
        # ==========================================
        book.status = BookStatus.OCR_CLEANING
        db.commit()
        
        # Setup path
        filename_no_ext = os.path.splitext(book.filename)[0]
        cleaned_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}.json")
        
        logger.info(f"[Book {book_id}] Avvio Pulizia OCR tramite LLM...")
        success = run_llm_cleaner(book.raw_file_path, cleaned_path)
        
        if not success:
            raise Exception("Fallimento durante la pulizia OCR tramite LLM")
            
        book.clean_file_path = cleaned_path
        db.commit()
        
        # ==========================================
        # FASE 2: NER EXTRACTION (HuggingFace)
        # ==========================================
        book.status = BookStatus.NER_EXTRACTION
        db.commit()
        
        logger.info(f"[Book {book_id}] Avvio NER Extraction locale...")
        ner_path = os.path.join(DATA_DIR, "ner", f"{filename_no_ext}_entities.json")
        success_ner = extract_ner_from_file(cleaned_path, ner_path)
        
        if not success_ner:
            raise Exception("Fallimento durante l'estrazione NER")
            
        book.ner_file_path = ner_path
        db.commit()
        
        # ==========================================
        # FASE 3: SEMANTIC CHUNKING E CHAPTERING
        # ==========================================
        book.status = BookStatus.SEMANTIC_CHUNKING
        db.commit()
        
        logger.info(f"[Book {book_id}] Avvio Semantic Chunking (Bedrock)...")
        chunk_dir = os.path.join(DATA_DIR, "semantic", filename_no_ext)
        manifest_chunk_path = run_semantic_chunker(filename_no_ext, cleaned_path, ner_path, os.path.join(DATA_DIR, "semantic"))
        book.chunk_manifest_path = manifest_chunk_path
        db.commit()
        
        book.status = BookStatus.CHAPTER_GROUPING
        db.commit()
        
        logger.info(f"[Book {book_id}] Avvio Chapter Grouper (Bedrock)...")
        manifest_chapters_path = run_chapter_grouper(filename_no_ext, chunk_dir)
        book.chapter_manifest_path = manifest_chapters_path
        db.commit()
        
        logger.info(f"[Book {book_id}] Fase 3 completata. Capitoli in {manifest_chapters_path}")
        
        # Salvataggio Capitoli nel DB per i Riassunti futuri
        logger.info(f"[Book {book_id}] Salvataggio capitoli nel database...")
        from database import Chapter, Summary
        with open(manifest_chapters_path, "r", encoding="utf-8") as f:
            chapter_manifest = json.load(f)
            
        cap_models = []
        for cap_data in chapter_manifest.get("chapters", []):
            new_chapter = Chapter(
                book_id=book.id,
                chapter_id_num=cap_data["chapter_id"],
                title=cap_data["title"],
                char_start=cap_data["char_start"],
                char_end=cap_data["char_end"]
            )
            db.add(new_chapter)
            cap_models.append((new_chapter, cap_data))
        db.commit()
        
        # ==========================================
        # FASE 5: SUMMARIZING
        # ==========================================
        book.status = BookStatus.SUMMARIZING
        db.commit()
        
        logger.info(f"[Book {book_id}] Avvio Generazione Riassunti...")
        chapters_dir = os.path.join(DATA_DIR, "chapters", filename_no_ext)
        
        for chapter_model, cap_data in cap_models:
            chapter_id_num = cap_data["chapter_id"]
            title = cap_data["title"]
            chunk_ids = cap_data.get("chunk_ids", [])
            
            # Carica i chunk per questo capitolo
            chunks_data = []
            for cid in chunk_ids:
                chunk_file = os.path.join(chapters_dir, str(chapter_id_num), f"chunk_{cid:03d}.json")
                if os.path.exists(chunk_file):
                    with open(chunk_file, "r", encoding="utf-8") as f:
                        chunks_data.append(json.load(f))
            
            # Genera il riassunto narrativo (Level 0)
            summary_text = generate_chapter_summary(title, chunks_data)
            
            if summary_text:
                new_summary = Summary(
                    chapter_id=chapter_model.id,
                    level=0,
                    content=summary_text
                )
                db.add(new_summary)
        
        db.commit()
        
        # Alla fine
        book.status = BookStatus.COMPLETED
        db.commit()

    except Exception as e:
        logger.error(f"Errore fatale pipeline per libro {book_id}: {e}")
        book.status = BookStatus.ERROR
        db.commit()
