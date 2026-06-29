import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.database import SessionLocal, Book
from app.semantic.chunker import run_semantic_chunker
from app.semantic.chapter_grouper import run_chapter_grouper

db = SessionLocal()
book = db.query(Book).filter(Book.ner_file_path != None).first()
if book:
    print(f"Testing on book: {book.title}")
    filename_no_ext = os.path.splitext(book.filename)[0]
    out_dir = os.path.join(BASE_DIR, "data", "semantic")
    
    # Run Chunker
    print("Running Chunker...")
    manifest_chunk = run_semantic_chunker(filename_no_ext, book.clean_file_path, book.ner_file_path, out_dir)
    print(f"Chunk manifest: {manifest_chunk}")
    
    if manifest_chunk:
        print("Running Grouper...")
        chunk_dir = os.path.dirname(manifest_chunk)
        manifest_chapters = run_chapter_grouper(filename_no_ext, chunk_dir)
        print(f"Chapter manifest: {manifest_chapters}")
else:
    print("No book with NER found.")
