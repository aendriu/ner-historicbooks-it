import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Ollama LLM Configuration
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "localhost")
if OLLAMA_HOST == "inserisci_qui_ip_del_server" or not OLLAMA_HOST.strip():
    OLLAMA_HOST = "localhost"
OLLAMA_PORT = os.getenv("OLLAMA_PORT", "11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# NER Configuration
NER_MODEL_NAME = os.getenv("NER_MODEL_NAME", "aendriu/bert-ner-italian-historical")
NER_SCORE_THRESHOLD = float(os.getenv("NER_SCORE_THRESHOLD", "0.65"))
NER_MIN_ENTITY_CHARS = int(os.getenv("NER_MIN_ENTITY_CHARS", "3"))

# Semantic Chunking
SEMANTIC_EMBEDDING_MODEL = os.getenv("SEMANTIC_EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
SEMANTIC_SIMILARITY_THRESHOLD = float(os.getenv("SEMANTIC_SIMILARITY_THRESHOLD", "0.5"))

# Database
DB_PATH = os.path.join(BASE_DIR, os.getenv("DB_FILENAME", "historicbooks.db"))
