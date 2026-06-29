from app.semantic.summarizer import generate_chapter_summary
print("Calling generate_chapter_summary...")
res = generate_chapter_summary("Test Title", [{"text": "Hello world", "topic_hint": "Test"}])
print("Result:", repr(res))
