"""
Data retrieval endpoints for books.

All endpoints here are read-only GET routes that return processed artefacts
(text, NER, chunks, chapter chunks, summaries). They were extracted from
pipeline.py to keep that module focused on pipeline-running POST endpoints.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import os
import json
import glob
import logging

from app.database import SessionLocal, Book, Chapter, Summary
from app.config import DATA_DIR

logger = logging.getLogger("uvicorn.error")

CHAPTERS_DIR = os.path.join(DATA_DIR, "chapters")

router = APIRouter(tags=["data"])


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
# TEXT
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/books/{book_id}/text")
def get_book_text(book_id: int, db: Session = Depends(get_db)):
    """Restituisce il testo pulito e grezzo del libro."""
    book = _get_book_or_404(book_id, db)

    text = ""
    if book.clean_file_path and os.path.exists(book.clean_file_path):
        with open(book.clean_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        text = data.get("contenuto", data.get("text", data.get("content", "")))

    raw_text = ""
    if book.raw_file_path and os.path.exists(book.raw_file_path):
        with open(book.raw_file_path, "r", encoding="utf-8") as f:
            if book.raw_file_path.endswith(".json"):
                try:
                    raw_data = json.load(f)
                    raw_text = raw_data.get("contenuto", raw_data.get("text", raw_data.get("content", "")))
                except Exception:
                    f.seek(0)
                    raw_text = f.read()
            else:
                raw_text = f.read()

    return {
        "book_id": book_id,
        "title": book.title,
        "author": book.author,
        "char_count": len(text),
        "raw_char_count": len(raw_text),
        "preview": text[:50000] if text else "",
        "raw_preview": raw_text[:50000] if raw_text else "",
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NER
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/books/{book_id}/ner")
def get_book_ner(book_id: int, db: Session = Depends(get_db)):
    """Restituisce i risultati NER del libro."""
    book = _get_book_or_404(book_id, db)
    if not book.ner_file_path or not os.path.exists(book.ner_file_path):
        raise HTTPException(404, "NER non ancora eseguito.")
    with open(book.ner_file_path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═══════════════════════════════════════════════════════════════════════════════
# CHUNKS
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/books/{book_id}/chunks")
def get_book_chunks(book_id: int, db: Session = Depends(get_db)):
    """Tutti i chunk semantici del libro."""
    book = _get_book_or_404(book_id, db)
    if not book.chunk_manifest_path or not os.path.exists(book.chunk_manifest_path):
        raise HTTPException(404, "Chunk manifest non disponibile.")
    chunk_dir = os.path.dirname(book.chunk_manifest_path)
    chunks = []
    for fp in sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.json"))):
        with open(fp, "r", encoding="utf-8") as f:
            chunks.append(json.load(f))
    return {"total": len(chunks), "chunks": chunks}


@router.get("/api/books/{book_id}/semantic-chunks")
def get_semantic_chunks(book_id: int, method: str = "embed", db: Session = Depends(get_db)):
    """Restituisce i chunk semantici per il metodo specificato (embed/ner)."""
    book = _get_book_or_404(book_id, db)
    filename_no_ext = os.path.splitext(book.filename)[0]
    
    subdir = "embed_method" if method == "embed" else "ner_method"
    chunk_dir = os.path.join(DATA_DIR, "semantic", subdir, filename_no_ext)
    
    if not os.path.exists(chunk_dir):
        raise HTTPException(404, f"Chunking '{method}' non trovato.")
        
    chunks = []
    for fp in sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.json"))):
        with open(fp, "r", encoding="utf-8") as f:
            chunks.append(json.load(f))
    return chunks


@router.get("/api/books/{book_id}/chapters/{chapter_id}/chunks")
def get_chapter_chunks(book_id: int, chapter_id: int, db: Session = Depends(get_db)):
    """Tutti i chunk semantici di un singolo capitolo."""
    book = _get_book_or_404(book_id, db)
    filename_no_ext = os.path.splitext(book.filename)[0]
    chapter_dir = os.path.join(CHAPTERS_DIR, filename_no_ext, str(chapter_id))
    if not os.path.exists(chapter_dir):
        raise HTTPException(404, "Cartella capitolo non trovata")
    chunks = []
    for fp in sorted(glob.glob(os.path.join(chapter_dir, "chunk_*.json"))):
        with open(fp, "r", encoding="utf-8") as f:
            chunks.append(json.load(f))
    return chunks


# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARIES
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/api/books/{book_id}/chapters/{chapter_id_num}/summary")
def get_chapter_summary(book_id: int, chapter_id_num: int, db: Session = Depends(get_db)):
    """Restituisce il riassunto di un singolo capitolo."""
    chapter = db.query(Chapter).filter(
        Chapter.book_id == book_id, Chapter.chapter_id_num == chapter_id_num
    ).first()
    if not chapter:
        raise HTTPException(404, "Capitolo non trovato")
    summary = db.query(Summary).filter(
        Summary.chapter_id == chapter.id, Summary.level == 0
    ).first()
    if not summary:
        raise HTTPException(404, "Riassunto non ancora generato")
    return {"content": summary.content, "level": summary.level}


@router.get("/api/books/{book_id}/summaries")
def get_all_summaries(book_id: int, db: Session = Depends(get_db)):
    """Tutti i riassunti dei capitoli del libro e la sinossi globale."""
    chapters = db.query(Chapter).filter(
        Chapter.book_id == book_id
    ).order_by(Chapter.chapter_id_num).all()
    
    chapter_summaries = [
        {
            "chapter_id": ch.chapter_id_num,
            "title": ch.title,
            "summary": (
                db.query(Summary)
                .filter(Summary.chapter_id == ch.id, Summary.level == 0)
                .first()
            ),
        }
        for ch in chapters
    ]
    
    book_summary = db.query(Summary).filter(
        Summary.book_id == book_id, Summary.level == 1
    ).first()
    
    return {
        "book_summary": book_summary.content if book_summary else None,
        "chapters": chapter_summaries
    }
