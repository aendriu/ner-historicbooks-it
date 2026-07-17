import os

# Base paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

class Settings:
    """Configurazione centralizzata dell'applicazione.

    Legge i parametri da variabili d'ambiente al momento dell'istanziazione.
    I valori possono essere modificati a runtime dal frontend.
    """

    def __init__(self) -> None:
        """Inizializza i parametri di configurazione dalle variabili d'ambiente."""
        self.OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "localhost")
        if self.OLLAMA_HOST == "inserisci_qui_ip_del_server" or not self.OLLAMA_HOST.strip():
            self.OLLAMA_HOST = "localhost"
        self.OLLAMA_PORT: str = os.getenv("OLLAMA_PORT", "11434")
        self.OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3.5:9b")
        self.EMBED_MODEL: str = os.getenv("SEMANTIC_EMBEDDING_MODEL", "bge-m3")

    def get_base_url(self) -> str:
        """Costruisce l'URL base del server Ollama dalla configurazione corrente.

        Returns:
            URL base senza slash finale (es. 'http://localhost:11434').
        """
        host = self.OLLAMA_HOST.rstrip("/")
        if host.startswith(("http://", "https://")):
            return host
        return f"http://{host}:{self.OLLAMA_PORT}"

settings = Settings()

# NER Configuration
NER_MODEL_NAME = os.getenv("NER_MODEL_NAME", "aendriu/bert-ner-italian-historical")
NER_SCORE_THRESHOLD = float(os.getenv("NER_SCORE_THRESHOLD", "0.65"))
NER_MIN_ENTITY_CHARS = int(os.getenv("NER_MIN_ENTITY_CHARS", "3"))

# Semantic Chunking (soglia — il modello è in settings.EMBED_MODEL)
SEMANTIC_SIMILARITY_THRESHOLD = float(os.getenv("SEMANTIC_SIMILARITY_THRESHOLD", "0.5"))

# Database
DB_PATH = os.path.join(BASE_DIR, os.getenv("DB_FILENAME", "historicbooks.db"))
