from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
import os, shutil, uuid, json, glob, logging

from database import SessionLocal, engine, Base, Book, BookStatus, Chapter, Summary
from services import (
    process_book_pipeline,
)
from ner.ner_extractor import extract_ner_from_file
from semantic.chunker import run_semantic_chunker
from semantic.chapter_grouper import run_chapter_grouper
from semantic.summarizer import generate_chapter_summary

logger = logging.getLogger("uvicorn.error")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_BACKEND = os.path.dirname(os.path.abspath(__file__))
DATA_DIR      = os.path.join(BASE_BACKEND, "data")
RAW_DIR       = os.path.join(DATA_DIR, "raw")
CLEANED_DIR   = os.path.join(DATA_DIR, "cleaned")
NER_DIR       = os.path.join(DATA_DIR, "ner")
SEMANTIC_DIR  = os.path.join(DATA_DIR, "semantic")
CHAPTERS_DIR  = os.path.join(DATA_DIR, "chapters")
CLEANER_OUT   = os.path.join(BASE_BACKEND, "cleaner", "output")

for d in [RAW_DIR, CLEANED_DIR, NER_DIR, SEMANTIC_DIR, CHAPTERS_DIR]:
    os.makedirs(d, exist_ok=True)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Historic Books Pipeline API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ═══════════════════════════════════════════════════════════════════════════════
# LIBRI
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/books")
def get_books(db: Session = Depends(get_db)):
    """Elenco di tutti i libri con stato pipeline."""
    books = db.query(Book).order_by(Book.created_at.desc()).all()
    return [
        {
            "id": b.id,
            "title": b.title,
            "author": b.author,
            "status": b.status.value,
            "created": b.created_at,
            "has_clean": bool(b.clean_file_path and os.path.exists(b.clean_file_path)),
            "has_ner": bool(b.ner_file_path and os.path.exists(b.ner_file_path)),
            "has_chunks": bool(b.chunk_manifest_path and os.path.exists(b.chunk_manifest_path)),
            "has_chapters": bool(b.chapter_manifest_path and os.path.exists(b.chapter_manifest_path)),
        }
        for b in books
    ]

@app.get("/api/books/{book_id}")
def get_book_details(book_id: int, db: Session = Depends(get_db)):
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Libro non trovato")
    return {
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "status": book.status.value,
        "raw_file": book.raw_file_path,
        "clean_file": book.clean_file_path,
        "ner_file": book.ner_file_path,
        "chunk_manifest": book.chunk_manifest_path,
        "chapter_manifest": book.chapter_manifest_path,
        "has_clean": bool(book.clean_file_path and os.path.exists(book.clean_file_path)),
        "has_ner": bool(book.ner_file_path and os.path.exists(book.ner_file_path)),
        "has_chunks": bool(book.chunk_manifest_path and os.path.exists(book.chunk_manifest_path)),
        "has_chapters": bool(book.chapter_manifest_path and os.path.exists(book.chapter_manifest_path)),
    }

# ── Upload raw file ────────────────────────────────────────────────────────────
@app.post("/api/books/upload")
async def upload_book(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Carica un file raw (txt/json) nel sistema."""
    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    file_path = os.path.join(RAW_DIR, safe_filename)
    with open(file_path, "wb") as buf:
        shutil.copyfileobj(file.file, buf)
    new_book = Book(
        title=file.filename,
        author="Sconosciuto",
        filename=safe_filename,
        status=BookStatus.UPLOADED,
        raw_file_path=file_path,
    )
    db.add(new_book)
    db.commit()
    db.refresh(new_book)
    return {"message": "Caricato.", "book_id": new_book.id}

# ── Scan pre-cleaned books ─────────────────────────────────────────────────────
@app.post("/api/scan")
def scan_cleaned_books(db: Session = Depends(get_db)):
    """Scansiona cleaner/output/ e importa i libri già puliti nel DB."""
    json_files = glob.glob(os.path.join(CLEANER_OUT, "*.json"))
    imported = 0
    for path in json_files:
        filename = os.path.basename(path)
        # Evita duplicati
        existing = db.query(Book).filter(Book.clean_file_path == path).first()
        if existing:
            continue
        # Leggi metadati
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            title  = data.get("title", filename.replace(".json", ""))
            author_obj = data.get("author", {})
            author = author_obj.get("name", "Sconosciuto") if isinstance(author_obj, dict) else str(author_obj)
        except Exception:
            title  = filename.replace(".json", "")
            author = "Sconosciuto"

        book = Book(
            title=title,
            author=author,
            filename=filename,
            status=BookStatus.OCR_CLEANING,   # già puliti
            clean_file_path=path,
        )
        db.add(book)
        imported += 1
    db.commit()
    return {"imported": imported, "total_found": len(json_files)}

# ═══════════════════════════════════════════════════════════════════════════════
# PIPELINE — step singoli
# ═══════════════════════════════════════════════════════════════════════════════

def _get_book_or_404(book_id: int, db: Session) -> Book:
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Libro non trovato")
    return book

# ── Progress Tracking ─────────────────────────────────────────────────────────
progress_store = {}

@app.get("/api/books/{book_id}/progress/{phase}")
def get_progress(book_id: int, phase: str):
    key = f"{book_id}_{phase}"
    return progress_store.get(key, {"status": "idle", "logs": []})

# ── Pipeline completa ──────────────────────────────────────────────────────────
@app.post("/api/books/{book_id}/run/all")
def run_all(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    book = _get_book_or_404(book_id, db)
    book.status = BookStatus.UPLOADED
    db.commit()
    background_tasks.add_task(process_book_pipeline, book.id, db)
    return {"message": "Pipeline completa avviata in background"}

# ── Solo OCR Cleaning ────────────────────────────────────────────────────────
@app.post("/api/books/{book_id}/run/ocr")
def run_ocr_only(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    book = _get_book_or_404(book_id, db)
    if not book.raw_file_path or not os.path.exists(book.raw_file_path):
        raise HTTPException(400, "Testo originale grezzo non disponibile.")

    def _do_ocr():
        progress_key = f"{book_id}_ocr"
        progress_store[progress_key] = {"status": "running", "logs": []}
        
        try:
            book.status = BookStatus.OCR_CLEANING
            db.commit()
            
            progress_store[progress_key]["logs"].append("Avvio pulizia OCR tramite preprocess_c...")
            
            # Setup path
            filename_no_ext = os.path.splitext(book.filename)[0]
            cleaned_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}.json")
            
            from ocr.llm_cleaner import run_llm_cleaner
            
            def _cb(current, total, detail=""):
                msg = f"[{current}/{total}] {detail}"
                progress_store[progress_key]["logs"].append(msg)
                
            success = run_llm_cleaner(book.raw_file_path, cleaned_path, progress_cb=_cb)
            
            if success and os.path.exists(cleaned_path):
                book.clean_file_path = cleaned_path
                book.has_clean = True
                book.status = BookStatus.COMPLETED
                db.commit()
                progress_store[progress_key]["logs"].append("Pulizia OCR completata con successo!")
                progress_store[progress_key]["status"] = "completed"
            else:
                book.status = BookStatus.ERROR
                db.commit()
                progress_store[progress_key]["status"] = "error"
                progress_store[progress_key]["logs"].append("Errore durante l'esecuzione del cleaner LLM.")
                
        except Exception as e:
            logger.error(f"OCR error: {e}")
            book.status = BookStatus.ERROR
            db.commit()
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {str(e)}")

    background_tasks.add_task(_do_ocr)
    return {"message": "Pulizia OCR avviata in background"}

# ── Solo NER ───────────────────────────────────────────────────────────────────
@app.post("/api/books/{book_id}/run/ner")
def run_ner(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    book = _get_book_or_404(book_id, db)
    if not book.clean_file_path or not os.path.exists(book.clean_file_path):
        raise HTTPException(400, "Testo pulito non disponibile. Esegui prima la pulizia OCR.")
    
    def _do_ner():
        progress_key = f"{book_id}_ner"
        progress_store[progress_key] = {"status": "running", "logs": []}
        def _cb(current, total, detail=""):
            msg = f"Elaborato chunk {current}/{total}"
            if isinstance(detail, int): msg += f" - trovate {detail} nuove entità"
            elif detail: msg += f" - {detail}"
            progress_store[progress_key]["logs"].append(msg)

        try:
            book.status = BookStatus.NER_EXTRACTION
            db.commit()
            filename_no_ext = os.path.splitext(book.filename)[0]
            ner_path = os.path.join(NER_DIR, f"{filename_no_ext}_entities.json")
            ok = extract_ner_from_file(book.clean_file_path, ner_path, progress_cb=_cb)
            if ok:
                book.ner_file_path = ner_path
                book.status = BookStatus.COMPLETED
                progress_store[progress_key]["status"] = "completed"
            else:
                book.status = BookStatus.ERROR
                progress_store[progress_key]["status"] = "error"
            db.commit()
        except Exception as e:
            logger.error(f"NER error: {e}")
            book.status = BookStatus.ERROR
            db.commit()
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {str(e)}")

    background_tasks.add_task(_do_ner)
    return {"message": "NER avviato in background"}

# ── Solo Chunking semantico ────────────────────────────────────────────────────
@app.post("/api/books/{book_id}/run/chunking")
def run_chunking(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
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

        try:
            book.status = BookStatus.SEMANTIC_CHUNKING
            db.commit()
            filename_no_ext = os.path.splitext(book.filename)[0]
            manifest_path = run_semantic_chunker(
                filename_no_ext,
                book.clean_file_path,
                book.ner_file_path,
                SEMANTIC_DIR,
                progress_cb=_cb
            )
            book.chunk_manifest_path = manifest_path
            book.status = BookStatus.COMPLETED
            progress_store[progress_key]["status"] = "completed"
            db.commit()
        except Exception as e:
            logger.error(f"Chunking error: {e}")
            book.status = BookStatus.ERROR
            db.commit()
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {str(e)}")

    background_tasks.add_task(_do_chunking)
    return {"message": "Chunking semantico avviato in background"}

# ── Solo Chapter Grouping ──────────────────────────────────────────────────────
@app.post("/api/books/{book_id}/run/chapters")
def run_chapters(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    book = _get_book_or_404(book_id, db)
    if not book.chunk_manifest_path or not os.path.exists(book.chunk_manifest_path):
        raise HTTPException(400, "Chunk manifest non disponibile. Esegui prima il chunking.")

    def _do_chapters():
        progress_key = f"{book_id}_chapters"
        progress_store[progress_key] = {"status": "running", "logs": []}
        def _cb(current, total, detail=""):
            progress_store[progress_key]["logs"].append(f"[{current}/{total}] {detail}")

        try:
            book.status = BookStatus.CHAPTER_GROUPING
            db.commit()
            filename_no_ext = os.path.splitext(book.filename)[0]
            chunk_dir = os.path.dirname(book.chunk_manifest_path)
            manifest_path = run_chapter_grouper(filename_no_ext, chunk_dir, progress_cb=_cb)
            book.chapter_manifest_path = manifest_path
            # Salva capitoli in DB
            with open(manifest_path, "r", encoding="utf-8") as f:
                ch_manifest = json.load(f)
            # Rimuovi vecchi capitoli
            db.query(Chapter).filter(Chapter.book_id == book.id).delete()
            for cap in ch_manifest.get("chapters", []):
                db.add(Chapter(
                    book_id=book.id,
                    chapter_id_num=cap["chapter_id"],
                    title=cap["title"],
                    char_start=cap.get("char_start", 0),
                    char_end=cap.get("char_end", 0),
                ))
            book.status = BookStatus.COMPLETED
            progress_store[progress_key]["status"] = "completed"
            db.commit()
        except Exception as e:
            logger.error(f"Chapter grouping error: {e}")
            book.status = BookStatus.ERROR
            db.commit()
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {str(e)}")

    background_tasks.add_task(_do_chapters)
    return {"message": "Chapter grouping avviato in background"}

# ── Solo Summarization ─────────────────────────────────────────────────────────
@app.post("/api/books/{book_id}/run/summaries")
def run_summaries(book_id: int, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    book = _get_book_or_404(book_id, db)
    chapters = db.query(Chapter).filter(Chapter.book_id == book_id).all()
    if not chapters:
        raise HTTPException(400, "Capitoli non disponibili. Esegui prima il chapter grouping.")

    def _do_summaries():
        progress_key = f"{book_id}_summaries"
        progress_store[progress_key] = {"status": "running", "logs": []}
        def _cb(current, total, detail=""):
            progress_store[progress_key]["logs"].append(f"Capitolo {current}/{total}: {detail}")

        try:
            book.status = BookStatus.SUMMARIZING
            db.commit()
            filename_no_ext = os.path.splitext(book.filename)[0]
            chapters_dir = os.path.join(CHAPTERS_DIR, filename_no_ext)
            tot_ch = len(chapters)
            for i, chapter in enumerate(chapters):
                _cb(i+1, tot_ch, f"Inizio generazione riassunto per '{chapter.title}'")
                # Leggi i chunk di questo capitolo
                cap_dir = os.path.join(chapters_dir, str(chapter.chapter_id_num))
                chunks_data = []
                if os.path.exists(cap_dir):
                    for cf in sorted(os.listdir(cap_dir)):
                        if cf.endswith(".json"):
                            with open(os.path.join(cap_dir, cf), "r", encoding="utf-8") as f:
                                chunks_data.append(json.load(f))
                # Elimina riassunto esistente
                db.query(Summary).filter(Summary.chapter_id == chapter.id, Summary.level == 0).delete()
                text = generate_chapter_summary(chapter.title, chunks_data)
                if text:
                    db.add(Summary(chapter_id=chapter.id, level=0, content=text))
                    _cb(i+1, tot_ch, f"Riassunto salvato con successo ({len(text)} caratteri)")
                else:
                    _cb(i+1, tot_ch, f"Nessun riassunto generato.")
            book.status = BookStatus.COMPLETED
            progress_store[progress_key]["status"] = "completed"
            db.commit()
        except Exception as e:
            logger.error(f"Summarization error: {e}")
            book.status = BookStatus.ERROR
            db.commit()
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore: {str(e)}")

    background_tasks.add_task(_do_summaries)
    return {"message": "Generazione riassunti avviata in background"}

# ═══════════════════════════════════════════════════════════════════════════════
# DATI DI FASE
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/api/books/{book_id}/text")
def get_book_text(book_id: int, db: Session = Depends(get_db)):
    """Restituisce il testo del libro (prime 50k chars per performance)."""
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

@app.get("/api/books/{book_id}/ner")
def get_book_ner(book_id: int, db: Session = Depends(get_db)):
    book = _get_book_or_404(book_id, db)
    if not book.ner_file_path or not os.path.exists(book.ner_file_path):
        raise HTTPException(404, "NER non ancora eseguito.")
    with open(book.ner_file_path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/api/books/{book_id}/chunks")
def get_book_chunks(book_id: int, db: Session = Depends(get_db)):
    """Tutti i chunk semantici del libro (dal manifest)."""
    book = _get_book_or_404(book_id, db)
    if not book.chunk_manifest_path or not os.path.exists(book.chunk_manifest_path):
        raise HTTPException(404, "Chunk manifest non disponibile.")
    chunk_dir = os.path.dirname(book.chunk_manifest_path)
    chunks = []
    for fp in sorted(glob.glob(os.path.join(chunk_dir, "chunk_*.json"))):
        with open(fp, "r", encoding="utf-8") as f:
            chunks.append(json.load(f))
    return {"total": len(chunks), "chunks": chunks}

@app.get("/api/books/{book_id}/chapters")
def get_book_chapters(book_id: int, db: Session = Depends(get_db)):
    book = _get_book_or_404(book_id, db)
    if not book.chapter_manifest_path or not os.path.exists(book.chapter_manifest_path):
        raise HTTPException(404, "Chapter manifest non disponibile.")
    with open(book.chapter_manifest_path, "r", encoding="utf-8") as f:
        return json.load(f)

@app.get("/api/books/{book_id}/chapters/{chapter_id}/chunks")
def get_chapter_chunks(book_id: int, chapter_id: int, db: Session = Depends(get_db)):
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

@app.get("/api/books/{book_id}/chapters/{chapter_id_num}/summary")
def get_chapter_summary(book_id: int, chapter_id_num: int, db: Session = Depends(get_db)):
    chapter = db.query(Chapter).filter(
        Chapter.book_id == book_id,
        Chapter.chapter_id_num == chapter_id_num
    ).first()
    if not chapter:
        raise HTTPException(404, "Capitolo non trovato")
    summary = db.query(Summary).filter(Summary.chapter_id == chapter.id, Summary.level == 0).first()
    if not summary:
        raise HTTPException(404, "Riassunto non ancora generato")
    return {"content": summary.content, "level": summary.level}

@app.get("/api/books/{book_id}/summaries")
def get_all_summaries(book_id: int, db: Session = Depends(get_db)):
    """Tutti i riassunti dei capitoli del libro."""
    chapters = db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.chapter_id_num).all()
    result = []
    for ch in chapters:
        summary = db.query(Summary).filter(Summary.chapter_id == ch.id, Summary.level == 0).first()
        result.append({
            "chapter_id": ch.chapter_id_num,
            "title": ch.title,
            "summary": summary.content if summary else None,
        })
    return result

@app.post("/api/batch/run/{phase}")
def run_batch_phase(phase: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Avvia in background l'esecuzione di una fase per tutti i libri idonei."""
    progress_key = f"batch_{phase}"
    if progress_store.get(progress_key, {}).get("status") == "running":
        return {"message": f"Batch {phase} già in esecuzione.", "status": "running"}
        
    books = db.query(Book).all()
    
    # Filtriamo i libri idonei a seconda della fase
    target_books = []
    if phase == "ocr":
        target_books = [b for b in books if not b.clean_file_path]
    elif phase == "ner":
        target_books = [b for b in books if b.clean_file_path and not b.ner_file_path]
    elif phase == "chunking":
        target_books = [b for b in books if b.ner_file_path and not b.chunk_manifest_path]
    elif phase == "chapters":
        target_books = [b for b in books if b.chunk_manifest_path and not b.chapter_manifest_path]
    elif phase == "summaries":
        target_books = [b for b in books if b.chapter_manifest_path] # Da migliorare per non rifarli se già esistono, ma ok per ora
    else:
        raise HTTPException(400, "Fase sconosciuta")

    if not target_books:
        progress_store[progress_key] = {"status": "completed", "logs": ["Nessun libro idoneo per questa fase."]}
        return {"message": "Nessun libro idoneo.", "status": "completed"}

    progress_store[progress_key] = {"status": "running", "logs": [f"Avvio batch {phase} su {len(target_books)} libri."]}

    # Creiamo una nuova sessione per il thread in background
    def _do_batch():
        db_session = SessionLocal()
        try:
            for idx, b in enumerate(target_books):
                book = db_session.query(Book).filter(Book.id == b.id).first()
                if not book:
                    continue
                
                log_prefix = f"[Libro {idx+1}/{len(target_books)} - {book.title}]"
                progress_store[progress_key]["logs"].append(f"{log_prefix} Inizio elaborazione...")
                
                filename_no_ext = os.path.splitext(book.filename)[0]
                
                if phase == "ocr":
                    book.status = BookStatus.OCR_CLEANING
                    db_session.commit()
                    cleaned_path = os.path.join(DATA_DIR, "cleaned", f"{filename_no_ext}.json")
                    from ocr.llm_cleaner import run_llm_cleaner
                    def _cb(c, t, d=""): progress_store[progress_key]["logs"][-1] = f"{log_prefix} [{c}/{t}] {d}"
                    success = run_llm_cleaner(book.raw_file_path, cleaned_path, progress_cb=_cb)
                    if success and os.path.exists(cleaned_path):
                        book.clean_file_path = cleaned_path
                        book.has_clean = True
                        book.status = BookStatus.COMPLETED
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Completato!")
                    else:
                        book.status = BookStatus.ERROR
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Errore!")
                        
                elif phase == "ner":
                    book.status = BookStatus.NER_EXTRACTION
                    db_session.commit()
                    ner_path = os.path.join(DATA_DIR, "ner", f"{filename_no_ext}_entities.json")
                    from ner.ner_extractor import extract_ner_from_file
                    success = extract_ner_from_file(book.clean_file_path, ner_path)
                    if success and os.path.exists(ner_path):
                        book.ner_file_path = ner_path
                        book.has_ner = True
                        book.status = BookStatus.COMPLETED
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Completato!")
                    else:
                        book.status = BookStatus.ERROR
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Errore!")
                        
                elif phase == "chunking":
                    book.status = BookStatus.SEMANTIC_CHUNKING
                    db_session.commit()
                    from semantic.chunker import run_semantic_chunker
                    def _cb_chunk(c, t, d=""): progress_store[progress_key]["logs"][-1] = f"{log_prefix} [{c}/{t}] {d}"
                    manifest_path = run_semantic_chunker(filename_no_ext, book.clean_file_path, book.ner_file_path, os.path.join(DATA_DIR, "semantic"), progress_cb=_cb_chunk)
                    if manifest_path:
                        book.chunk_manifest_path = manifest_path
                        book.status = BookStatus.COMPLETED
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Completato!")
                    else:
                        book.status = BookStatus.ERROR
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Errore!")
                        
                elif phase == "chapters":
                    book.status = BookStatus.CHAPTER_GROUPING
                    db_session.commit()
                    from semantic.chapter_grouper import run_chapter_grouper
                    chunk_dir = os.path.join(DATA_DIR, "semantic", filename_no_ext)
                    manifest_chapters = run_chapter_grouper(filename_no_ext, chunk_dir)
                    if manifest_chapters:
                        book.chapter_manifest_path = manifest_chapters
                        from database import Chapter
                        with open(manifest_chapters, "r", encoding="utf-8") as f:
                            cdata = json.load(f)
                        for cd in cdata.get("chapters", []):
                            if not db_session.query(Chapter).filter_by(book_id=book.id, chapter_id_num=cd["chapter_id"]).first():
                                nc = Chapter(book_id=book.id, chapter_id_num=cd["chapter_id"], title=cd["title"], char_start=cd["char_start"], char_end=cd["char_end"])
                                db_session.add(nc)
                        book.status = BookStatus.COMPLETED
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Completato!")
                    else:
                        book.status = BookStatus.ERROR
                        db_session.commit()
                        progress_store[progress_key]["logs"].append(f"{log_prefix} Errore!")
                        
                elif phase == "summaries":
                    book.status = BookStatus.SUMMARIZING
                    db_session.commit()
                    from semantic.summarizer import generate_chapter_summary
                    from database import Chapter, Summary
                    chapters_dir = os.path.join(DATA_DIR, "chapters", filename_no_ext)
                    caps = db_session.query(Chapter).filter(Chapter.book_id == book.id).all()
                    
                    with open(book.chapter_manifest_path, "r", encoding="utf-8") as f:
                        cmanifest = json.load(f)
                        
                    for ch_model in caps:
                        cd_info = next((c for c in cmanifest.get("chapters", []) if c["chapter_id"] == ch_model.chapter_id_num), None)
                        if not cd_info: continue
                        if db_session.query(Summary).filter_by(chapter_id=ch_model.id, level=0).first(): continue
                        
                        chunks_data = []
                        for cid in cd_info.get("chunk_ids", []):
                            cf = os.path.join(chapters_dir, str(ch_model.chapter_id_num), f"chunk_{cid:03d}.json")
                            if os.path.exists(cf):
                                with open(cf, "r", encoding="utf-8") as x: chunks_data.append(json.load(x))
                        stext = generate_chapter_summary(ch_model.title, chunks_data)
                        if stext:
                            db_session.add(Summary(chapter_id=ch_model.id, level=0, content=stext))
                            
                    book.status = BookStatus.COMPLETED
                    db_session.commit()
                    progress_store[progress_key]["logs"].append(f"{log_prefix} Completato!")
                    
            progress_store[progress_key]["status"] = "completed"
            progress_store[progress_key]["logs"].append("Tutti i libri completati!")
        except Exception as e:
            logger.error(f"Batch {phase} error: {e}")
            progress_store[progress_key]["status"] = "error"
            progress_store[progress_key]["logs"].append(f"Errore fatale nel batch: {e}")
        finally:
            db_session.close()

    background_tasks.add_task(_do_batch)
    return {"message": "Batch iniziato in background", "status": "running"}

@app.get("/api/batch/progress/{phase}")
def get_batch_progress(phase: str):
    progress_key = f"batch_{phase}"
    data = progress_store.get(progress_key, {"status": "idle", "logs": []})
    return data

