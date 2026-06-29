import os
import io
import json
import zipfile
import shutil
import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import SessionLocal, Book, Chapter, Summary
from app.config import DATA_DIR

router = APIRouter(prefix="/api/books", tags=["books"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

RAW_DIR = os.path.join(DATA_DIR, "raw")

@router.get("")
def get_books(db: Session = Depends(get_db)):
    """Elenco di tutti i libri con stato pipeline."""
    books = db.query(Book).order_by(Book.created_at.desc()).all()
    valid_books = []
    
    for b in books:
        if not b.raw_file_path or not os.path.exists(b.raw_file_path):
            # Se il file fisico non esiste più (es. cancellato a mano), rimuovi la riga orfana dal DB
            db.delete(b)
            continue
        valid_books.append({
            "id": b.id,
            "title": b.title,
            "author": b.author,
            "status": b.status.value,
            "created": b.created_at,
            "has_clean": bool(b.clean_file_path and os.path.exists(b.clean_file_path)),
            "has_ner": bool(b.ner_file_path and os.path.exists(b.ner_file_path)),
            "has_chunks": bool(b.chunk_manifest_path and os.path.exists(b.chunk_manifest_path)),
            "has_chapters": bool(b.chapter_manifest_path and os.path.exists(b.chapter_manifest_path)),
        })
    
    db.commit() # Salva le eventuali cancellazioni
    return valid_books

@router.get("/{book_id}")
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

@router.post("/upload")
async def upload_book(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Carica un file raw nel sistema e lo converte in JSON se è testo."""
    safe_filename = f"{uuid.uuid4().hex[:8]}_{file.filename}"
    
    # Assicurati che l'estensione finale sia .json
    if not safe_filename.endswith(".json"):
        safe_filename += ".json"
        
    file_path = os.path.join(RAW_DIR, safe_filename)
    
    content_bytes = await file.read()
    
    # Prova a parsare come JSON. Se fallisce, trattalo come testo crudo.
    try:
        data = json.loads(content_bytes.decode('utf-8'))
        if "contenuto" not in data and "text" in data:
            data["contenuto"] = data.pop("text")
        elif "contenuto" not in data and "content" in data:
            data["contenuto"] = data.pop("content")
    except Exception:
        data = {"contenuto": content_bytes.decode('utf-8', errors='replace')}
        
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        
    # Evita duplicati: se esiste già un libro con lo stesso nome, eliminalo dal DB
    existing = db.query(Book).filter(Book.title == file.filename).first()
    if existing:
        db.delete(existing)
        db.commit()
        
    new_book = Book(
        title=file.filename,
        author="Sconosciuto",
        filename=safe_filename,
        raw_file_path=file_path
    )
    db.add(new_book)
    db.commit()
    return {"status": "ok", "book_id": new_book.id}


@router.get("/{book_id}/export")
def export_book(book_id: int, db: Session = Depends(get_db)):
    """Esporta tutto il disponibile per un libro in un file ZIP strutturato."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Libro non trovato")

    # Nome base cartella dentro lo ZIP
    safe_title = "".join(c if c.isalnum() or c in (' ', '-', '_') else '_' for c in book.title)
    safe_title = safe_title.strip()[:60]
    root = safe_title

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:

        # ── 00_originale ────────────────────────────────────────────────────────
        if book.raw_file_path and os.path.exists(book.raw_file_path):
            with open(book.raw_file_path, "r", encoding="utf-8") as f:
                try:
                    raw_data = json.load(f)
                    zf.writestr(f"{root}/00_originale/originale.json",
                                json.dumps(raw_data, ensure_ascii=False, indent=2))
                    zf.writestr(f"{root}/00_originale/originale.txt",
                                raw_data.get("contenuto", ""))
                except json.JSONDecodeError:
                    f.seek(0)
                    zf.writestr(f"{root}/00_originale/originale.txt", f.read())

        # ── 01_testo_pulito ─────────────────────────────────────────────────────
        if book.clean_file_path and os.path.exists(book.clean_file_path):
            with open(book.clean_file_path, "r", encoding="utf-8") as f:
                clean_data = json.load(f)
            zf.writestr(f"{root}/01_testo_pulito/testo_pulito.json",
                        json.dumps(clean_data, ensure_ascii=False, indent=2))
            zf.writestr(f"{root}/01_testo_pulito/testo_pulito.txt",
                        clean_data.get("contenuto", ""))

        # ── 02_entita_ner ───────────────────────────────────────────────────────
        if book.ner_file_path and os.path.exists(book.ner_file_path):
            with open(book.ner_file_path, "r", encoding="utf-8") as f:
                ner_data = json.load(f)
            zf.writestr(f"{root}/02_entita_ner/entita.json",
                        json.dumps(ner_data, ensure_ascii=False, indent=2))
            # Anche come .csv tabellare
            entities = ner_data.get("entities", [])
            csv_lines = ["parola,etichetta,score,char_start,char_end"]
            for e in entities:
                csv_lines.append(
                    f"{e.get('word','')},{e.get('label','')},{e.get('score',0):.4f},{e.get('start',0)},{e.get('end',0)}"
                )
            zf.writestr(f"{root}/02_entita_ner/entita.csv", "\n".join(csv_lines))

        # ── 03_chunks_semantici ─────────────────────────────────────────────────
        if book.chunk_manifest_path and os.path.exists(book.chunk_manifest_path):
            chunk_dir = os.path.dirname(book.chunk_manifest_path)
            with open(book.chunk_manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            zf.writestr(f"{root}/03_chunks_semantici/manifest.json",
                        json.dumps(manifest, ensure_ascii=False, indent=2))
            # Ogni chunk come file separato
            for chunk_info in manifest.get("chunks", []):
                cid = chunk_info["chunk_id"]
                chunk_file = os.path.join(chunk_dir, f"chunk_{cid:03d}.json")
                if os.path.exists(chunk_file):
                    with open(chunk_file, "r", encoding="utf-8") as f:
                        chunk_data = json.load(f)
                    zf.writestr(
                        f"{root}/03_chunks_semantici/chunk_{cid:03d}.json",
                        json.dumps(chunk_data, ensure_ascii=False, indent=2)
                    )

        # ── 04_capitoli ─────────────────────────────────────────────────────────
        if book.chapter_manifest_path and os.path.exists(book.chapter_manifest_path):
            with open(book.chapter_manifest_path, "r", encoding="utf-8") as f:
                ch_manifest = json.load(f)
            zf.writestr(f"{root}/04_capitoli/capitoli.json",
                        json.dumps(ch_manifest, ensure_ascii=False, indent=2))

        # ── 05_riassunti ────────────────────────────────────────────────────────
        chapters = db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.chapter_id_num).all()
        if chapters:
            all_summaries_txt = []
            for ch in chapters:
                summaries = db.query(Summary).filter(Summary.chapter_id == ch.id).all()
                if summaries:
                    ch_title = ch.title or f"Capitolo {ch.chapter_id_num}"
                    ch_block = f"=== {ch_title} ===\n\n"
                    ch_block += "\n\n".join(s.content for s in summaries)
                    all_summaries_txt.append(ch_block)
                    zf.writestr(
                        f"{root}/05_riassunti/capitolo_{ch.chapter_id_num:03d}_{ch_title[:40]}.txt",
                        ch_block
                    )
            if all_summaries_txt:
                zf.writestr(
                    f"{root}/05_riassunti/_tutti_i_riassunti.txt",
                    "\n\n" + ("="*60) + "\n\n".join(all_summaries_txt)
                )

        # ── README ──────────────────────────────────────────────────────────────
        readme = f"""Esportazione: {book.title}
Autore: {book.author or 'N/D'}
Data export: {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC

Struttura cartelle:
  00_originale/        → Testo grezzo OCR (JSON + TXT)
  01_testo_pulito/     → Testo dopo pulizia LLM (JSON + TXT)
  02_entita_ner/       → Entità storiche estratte (JSON + CSV)
  03_chunks_semantici/ → Blocchi semantici del testo (un file per chunk)
  04_capitoli/         → Struttura dei capitoli rilevati
  05_riassunti/        → Riassunti per capitolo (TXT leggibili)
"""
        zf.writestr(f"{root}/README.txt", readme)

    buf.seek(0)
    zip_filename = f"{safe_title}_export.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename}"}
    )

@router.get("/{book_id}/chapters")
def get_book_chapters(book_id: int, db: Session = Depends(get_db)):
    """Restituisce i capitoli di un libro e i relativi riassunti."""
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Libro non trovato")
        
    chapters = db.query(Chapter).filter(Chapter.book_id == book_id).order_by(Chapter.chapter_id_num).all()
    result = []
    for ch in chapters:
        summaries = db.query(Summary).filter(Summary.chapter_id == ch.id).order_by(Summary.level).all()
        result.append({
            "id": ch.id,
            "chapter_id_num": ch.chapter_id_num,
            "title": ch.title,
            "char_start": ch.char_start,
            "char_end": ch.char_end,
            "summaries": [{"id": s.id, "level": s.level, "content": s.content} for s in summaries]
        })
    return result
