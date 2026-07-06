import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import books, pipeline, data, settings
from app.database import SessionLocal, Book, BookStatus
from app.config import DATA_DIR

logger = logging.getLogger("uvicorn.error")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Eseguito all'avvio del server: scansiona i file raw e li indicizza nel database"""
    db = SessionLocal()
    try:
        raw_dir = os.path.join(DATA_DIR, "raw")
        if os.path.exists(raw_dir):
            for filename in os.listdir(raw_dir):
                if filename.endswith(".json"):
                    existing = db.query(Book).filter(Book.filename == filename).first()
                    if not existing:
                        filepath = os.path.join(raw_dir, filename)
                        # Estrae un titolo leggibile dal nome file (es. 4a2f_promessi-sposi.json -> Promessi Sposi)
                        clean_title = filename.replace(".json", "")
                        if "_" in clean_title:
                            clean_title = clean_title.split("_", 1)[1]
                        clean_title = clean_title.replace("-", " ").title()
                        
                        new_book = Book(
                            filename=filename,
                            raw_file_path=filepath,
                            status=BookStatus.UPLOADED,
                            title=clean_title
                        )
                        db.add(new_book)
                        logger.info(f"Indicizzato nuovo libro grezzo: {filename}")
            db.commit()
    except Exception as e:
        logger.error(f"Errore durante la scansione iniziale: {e}")
    finally:
        db.close()
    yield

app = FastAPI(title="Historic Books Pipeline API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(books.router)
app.include_router(pipeline.router)
app.include_router(data.router)
app.include_router(settings.router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
