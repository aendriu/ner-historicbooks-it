import os
import io
import json
import textwrap
import zipfile
import shutil
import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database import Book, Chapter, Summary
from app.dependencies import get_db
from app.config import DATA_DIR

router = APIRouter(prefix="/api/books", tags=["books"])

RAW_DIR = os.path.join(DATA_DIR, "raw")

@router.get("")
def get_books(db: Session = Depends(get_db)):
    """Elenco di tutti i libri con stato pipeline."""
    books = db.query(Book).order_by(Book.created_at.desc()).all()
    valid_books = []
    
    for b in books:
        if not b.raw_file_path or not os.path.exists(b.raw_file_path):
            # INTENZIONALE: rimuove le righe orfane dal DB quando il file fisico
            # non esiste più (es. cancellato manualmente dal filesystem).
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
    """Restituisce i dettagli completi di un singolo libro."""
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
        
    # Evita duplicati: se esiste già un libro con lo stesso nome, eliminalo dal DB e cancella il vecchio file
    existing = db.query(Book).filter(Book.title == file.filename).first()
    if existing:
        if existing.raw_file_path and os.path.exists(existing.raw_file_path):
            os.remove(existing.raw_file_path)
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
        # Legge i file summaries_*.json direttamente dal disco (fonte primaria),
        # con fallback sui dati del database se i file non esistono.
        summaries_base = os.path.join(DATA_DIR, "summaries")
        summaries_found = False
        book_folder_name = os.path.splitext(book.filename)[0]  # es. '45e11373_promessi_sposi.txt'

        for method_dir in ("embed_method", "ner_method"):
            book_sum_dir = os.path.join(summaries_base, method_dir, book_folder_name)
            if not os.path.isdir(book_sum_dir):
                continue
            for fname in sorted(os.listdir(book_sum_dir)):
                if not fname.startswith("summaries_") or not fname.endswith(".json"):
                    continue
                fpath = os.path.join(book_sum_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        sum_data = json.load(f)
                except Exception:
                    continue

                model_name = fname.replace("summaries_", "").replace(".json", "")
                method_label = method_dir.replace("_method", "")
                subfolder = f"{root}/05_riassunti/{method_label}_{model_name}"

                # JSON completo
                zf.writestr(
                    f"{subfolder}/summaries.json",
                    json.dumps(sum_data, ensure_ascii=False, indent=2)
                )

                # Sinossi globale come JSON strutturato
                global_summary = sum_data.get("global_summary", "").strip()
                if global_summary:
                    ner_ret = sum_data.get("global_ner_retention", {})
                    riassunto_0 = {
                        "titolo":              book.title,
                        "autore":              book.author or "N/D",
                        "modello":             sum_data.get("model", "N/D"),
                        "metodo_chunking":     sum_data.get("method", "N/D"),
                        "data_generazione":    sum_data.get("created_at", "")[:10],
                        "num_caratteri":       len(global_summary),
                        "num_parole":          len(global_summary.split()),
                        "ner_retention_globale": {
                            "entita_uniche_totali": ner_ret.get("total_unique_entities", 0),
                            "entita_trovate":       ner_ret.get("found_in_global", 0),
                            "percentuale":          ner_ret.get("retention_percent", 0),
                        },
                        "testo": global_summary,
                    }
                    zf.writestr(
                        f"{subfolder}/lv0.json",
                        json.dumps(riassunto_0, ensure_ascii=False, indent=2)
                    )
                    # lv0.txt: solo il testo, ben formattato
                    paragraphs = global_summary.split("\n\n")
                    wrapped = "\n\n".join(
                        textwrap.fill(p.strip(), width=100)
                        for p in paragraphs if p.strip()
                    )
                    zf.writestr(f"{subfolder}/lv0.txt", wrapped)
                    summaries_found = True

                # Riassunti per capitolo semantico come file TXT concatenato
                sections = sum_data.get("sections", [])
                if sections:
                    all_parts = []
                    for sec in sections:
                        idx = sec.get("section_idx", "?")
                        topic = sec.get("topic_hint", f"Sezione {idx}")
                        text = sec.get("summary", "").strip()
                        if text:
                            all_parts.append(f"=== {topic} ===\n\n{text}")
                    if all_parts:
                        joined_txt = ("\n\n" + "="*60 + "\n\n").join(all_parts)
                        zf.writestr(
                            f"{subfolder}/chapter_summaries.txt",
                            joined_txt
                        )
                        # Anche come JSON con lista strutturata
                        chapters_json = [
                            {
                                "section_idx": sec.get("section_idx"),
                                "topic_hint":  sec.get("topic_hint"),
                                "summary":     sec.get("summary", "").strip(),
                            }
                            for sec in sections if sec.get("summary", "").strip()
                        ]
                        zf.writestr(
                            f"{subfolder}/chapter_summaries.json",
                            json.dumps(chapters_json, ensure_ascii=False, indent=2)
                        )
                        summaries_found = True

        # Fallback: se non ci sono file JSON su disco, usa il database
        if not summaries_found:
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
                if all_summaries_txt:
                    zf.writestr(
                        f"{root}/05_riassunti/_tutti_i_riassunti.txt",
                        "\n\n" + ("="*60 + "\n\n").join(all_summaries_txt)
                    )

        # ── README ──────────────────────────────────────────────────────────────
        # Titolo pulito: rimuove prefisso UUID e estensioni
        import re as _re
        clean_title = book.title
        clean_title = _re.sub(r'^[0-9a-f]{8}_', '', clean_title)          # rimuove UUID
        clean_title = _re.sub(r'\.(txt|json)$', '', clean_title, flags=_re.I)  # rimuove ext
        clean_title = clean_title.replace('_', ' ').replace('-', ' ').strip().title()

        # Raccoglie le sottocartelle reali generate in 05_riassunti
        subfolders_lines = []
        for method_dir in ("embed_method", "ner_method"):
            bdir = os.path.join(summaries_base, method_dir, book_folder_name)
            if not os.path.isdir(bdir):
                continue
            for fname in sorted(os.listdir(bdir)):
                if fname.startswith("summaries_") and fname.endswith(".json"):
                    model_label = fname.replace("summaries_", "").replace(".json", "")
                    method_label = method_dir.replace("_method", "")
                    subfolders_lines.append(f"    {method_label}_{model_label}/")

        subfolders_str = "\n".join(subfolders_lines) if subfolders_lines else "    (nessun riassunto generato)"

        author_line = f"Autore:       {book.author}\n" if book.author and book.author.lower() != "sconosciuto" else ""
        readme = (
            f"Opera:        {clean_title}\n"
            f"{author_line}"
            f"Data export:  {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n"
            f"\n"
            f"Struttura cartelle\n"
            f"==================\n"
            f"  00_originale/        Testo grezzo OCR originale (JSON + TXT)\n"
            f"  01_testo_pulito/     Testo dopo pulizia OCR (JSON + TXT)\n"
            f"  02_entita_ner/       Entita storiche estratte con BERT (JSON + CSV)\n"
            f"  03_chunks_semantici/ Blocchi semantici del testo (un file per chunk)\n"
            f"  04_capitoli/         Capitoli semantici rilevati\n"
            f"  05_riassunti/        Riassunti AI, organizzati per metodo e modello:\n"
            f"{subfolders_str}\n"
            f"\n"
            f"  Ogni sottocartella contiene:\n"
            f"    summaries.json         Dati grezzi completi\n"
            f"    lv0.json               Sinossi globale + metadati\n"
            f"    lv0.txt                Sinossi globale in prosa\n"
            f"    chapter_summaries.json Riassunti dei capitoli semantici (JSON)\n"
            f"    chapter_summaries.txt  Riassunti dei capitoli semantici (TXT)\n"
        )
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

@router.get("/{book_id}/global-summary")
def get_book_global_summary(book_id: int, db: Session = Depends(get_db)):
    """Restituisce il riassunto globale (sinossi) del libro."""
    summary = db.query(Summary).filter(Summary.book_id == book_id, Summary.level == 1).first()
    return {"content": summary.content if summary else None}
