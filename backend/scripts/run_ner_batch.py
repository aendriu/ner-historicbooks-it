import os
import sys
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.database import Book, BookStatus
from app.pipeline.ner import extract_ner_from_file

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DB_PATH = os.path.join(BASE_DIR, "historicbooks.db")
DATA_DIR = os.path.join(BASE_DIR, "data")
NER_DIR = os.path.join(DATA_DIR, "ner")

def main():
    os.makedirs(NER_DIR, exist_ok=True)
    
    engine = create_engine(f"sqlite:///{DB_PATH}")
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    # Trova i libri in stato NER_EXTRACTION
    books_to_process = session.query(Book).filter(Book.status == BookStatus.NER_EXTRACTION).all()
    
    if not books_to_process:
        logger.info("Nessun libro da processare in stato NER_EXTRACTION.")
        session.close()
        return

    logger.info(f"Trovati {len(books_to_process)} libri da processare con NER.")
    
    processed_count = 0
    for book in books_to_process:
        if not book.clean_file_path or not os.path.exists(book.clean_file_path):
            logger.warning(f"File pulito mancante per il libro: {book.title} (ID: {book.id})")
            continue
            
        filename_no_ext = os.path.splitext(book.filename)[0]
        ner_path = os.path.join(NER_DIR, f"{filename_no_ext}_entities.json")
        
        logger.info(f"Avvio estrazione NER per: {book.filename}")
        
        # Esegui estrazione NER locale
        success = extract_ner_from_file(book.clean_file_path, ner_path)
        
        if success:
            book.ner_file_path = ner_path
            book.status = BookStatus.SEMANTIC_CHUNKING  # Avanzamento allo stato successivo
            processed_count += 1
            logger.info(f"Completata estrazione per: {book.filename}")
        else:
            logger.error(f"Fallita estrazione NER per: {book.filename}")

    session.commit()
    session.close()
    
    logger.info(f"Elaborazione completata. {processed_count} libri processati con successo.")

if __name__ == "__main__":
    main()
