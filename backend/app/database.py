from sqlalchemy import create_engine, Column, Integer, String, DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import datetime
import enum
from app.config import DB_PATH

engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class BookStatus(enum.Enum):
    UPLOADED = "UPLOADED"
    OCR_CLEANING = "OCR_CLEANING"
    NER_EXTRACTION = "NER_EXTRACTION"
    SEMANTIC_CHUNKING = "SEMANTIC_CHUNKING"
    CHAPTER_GROUPING = "CHAPTER_GROUPING"
    SUMMARIZING = "SUMMARIZING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"

class Book(Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, index=True)
    author = Column(String, nullable=True)
    filename = Column(String, unique=True, index=True)  # Nome del file originale
    status = Column(Enum(BookStatus), default=BookStatus.UPLOADED)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_updated = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    # Percorsi dei file sul disco (il nostro "S3 locale")
    raw_file_path = Column(String, nullable=True)      # backend/data/raw/...
    clean_file_path = Column(String, nullable=True)    # backend/data/cleaned/...
    ner_file_path = Column(String, nullable=True)      # backend/data/ner/...
    chunk_manifest_path = Column(String, nullable=True) # backend/data/semantic/...
    chapter_manifest_path = Column(String, nullable=True)
    
    chapters = relationship("Chapter", back_populates="book", cascade="all, delete-orphan")

class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(Integer, primary_key=True, index=True)
    book_id = Column(Integer, ForeignKey("books.id"))
    chapter_id_num = Column(Integer)  # Es. 0, 1, 2...
    title = Column(String)
    char_start = Column(Integer)
    char_end = Column(Integer)
    
    book = relationship("Book", back_populates="chapters")
    summaries = relationship("Summary", back_populates="chapter", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_chapter_book_id", "book_id"),
    )

class Summary(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, index=True)
    chapter_id = Column(Integer, ForeignKey("chapters.id"))
    level = Column(Integer)  # 0 = base, 1 = intermedio, ecc.
    content = Column(String) # Il testo del riassunto
    
    chapter = relationship("Chapter", back_populates="summaries")

# Crea le tabelle nel file SQLite
Base.metadata.create_all(bind=engine)
