import os, glob, json, uuid, shutil
from sqlalchemy.orm import Session
from database import SessionLocal, Book, BookStatus

BASE_DIR = "/home/aendriu/Para/Project/tirocinio"
RAW_DIR = os.path.join(BASE_DIR, "backend", "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)

db = SessionLocal()

metadata_dir = os.path.join(BASE_DIR, "archive", "ner-historicbooks-it", "books", "metadata")
json_files = glob.glob(os.path.join(metadata_dir, "*.json"))

imported = 0
for path in json_files:
    filename = os.path.basename(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Ignora i file senza "contenuto"
        if "contenuto" not in data:
            continue

        title = data.get("title", filename.replace(".json", ""))
        author_obj = data.get("author", {})
        if isinstance(author_obj, dict):
            author = author_obj.get("name", "Sconosciuto")
        else:
            author = str(author_obj)
    except Exception as e:
        print(f"Errore lettura {filename}: {e}")
        continue
    
    # Crea un safe filename e copia in raw
    safe_filename = f"{uuid.uuid4().hex[:8]}_{filename}"
    raw_path = os.path.join(RAW_DIR, safe_filename)
    
    try:
        shutil.copy2(path, raw_path)
    except Exception as e:
        print(f"Errore copia {filename}: {e}")
        continue
    
    # Verifica se c'è già nel DB col path
    existing = db.query(Book).filter(Book.title == title).first()
    if existing:
        continue
        
    book = Book(
        title=title,
        author=author,
        filename=safe_filename,
        status=BookStatus.UPLOADED,
        raw_file_path=os.path.abspath(raw_path)
    )
    db.add(book)
    imported += 1

db.commit()
print(f"Importati {imported} libri come grezzi (UPLOADED) in {os.path.abspath(RAW_DIR)}")
