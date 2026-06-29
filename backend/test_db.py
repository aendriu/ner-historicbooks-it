import json
from app.database import SessionLocal, Summary, Chapter, Book
db = SessionLocal()
ch = db.query(Chapter).filter(Chapter.book_id == 97).first()
if ch:
    print("Found chapter:", ch.id)
    db.add(Summary(chapter_id=ch.id, level=0, content="Test summary"))
    db.commit()
    print("Committed. Count of summaries:", db.query(Summary).count())
else:
    print("No chapters found.")
db.close()
