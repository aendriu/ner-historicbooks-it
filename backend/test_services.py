import json, os
from app.config import DATA_DIR
from app.database import SessionLocal, Chapter, Book, Summary
from app.semantic.summarizer import generate_chapter_summary

db = SessionLocal()
book = db.query(Book).filter(Book.id == 97).first()
filename_no_ext = os.path.splitext(book.filename)[0]
chapters_dir = os.path.join(DATA_DIR, "chapters", filename_no_ext)
print("Chapters dir:", chapters_dir)

manifest_chapters = book.chapter_manifest_path
with open(manifest_chapters, "r", encoding="utf-8") as f:
    chapter_manifest = json.load(f)

cap_models = []
for cap_data in chapter_manifest.get("chapters", []):
    ch = db.query(Chapter).filter(Chapter.book_id == book.id, Chapter.chapter_id_num == cap_data["chapter_id"]).first()
    if ch:
        cap_models.append((ch, cap_data))

print("Caps found:", len(cap_models))

if len(cap_models) > 0:
    chapter_model, cap_data = cap_models[0]
    chunks_data = []
    for cid in cap_data.get("chunk_ids", []):
        chunk_file = os.path.join(chapters_dir, str(cap_data["chapter_id"]), f"chunk_{cid:03d}.json")
        if os.path.exists(chunk_file):
            with open(chunk_file, "r", encoding="utf-8") as f:
                chunks_data.append(json.load(f))
    
    print("Chunks loaded:", len(chunks_data))
    if chunks_data:
        summary_text = generate_chapter_summary(cap_data["title"], chunks_data)
        print("Summary generated! Len:", len(summary_text))
