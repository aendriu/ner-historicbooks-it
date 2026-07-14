"""Dipendenze condivise per i router FastAPI.

Contiene il generatore di sessione database e le utilità comuni
per evitare duplicazione tra i vari moduli router.
"""

import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal, Book

logger = logging.getLogger(__name__)


def get_db():
    """Generatore di sessione database per l'iniezione delle dipendenze FastAPI.

    Yields:
        Session: sessione SQLAlchemy attiva.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_book_or_404(book_id: int, db: Session) -> Book:
    """Recupera un libro dal database o solleva un errore 404.

    Args:
        book_id: identificativo univoco del libro.
        db: sessione database attiva.

    Returns:
        L'istanza Book corrispondente.

    Raises:
        HTTPException: se il libro non esiste (status 404).
    """
    book = db.query(Book).filter(Book.id == book_id).first()
    if not book:
        raise HTTPException(404, "Libro non trovato")
    return book
