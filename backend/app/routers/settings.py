from fastapi import APIRouter
from pydantic import BaseModel
import logging
import os

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])

class OllamaConfig(BaseModel):
    host: str
    port: str
    model: str = "qwen2.5:3b"
    embed_model: str = "bge-m3"

@router.post("/api/settings/ollama")
def update_ollama_settings(config: OllamaConfig):
    """
    Aggiorna l'URL del server Ollama in memoria E persiste nel .env.
    """
    import os, re
    host = config.host.strip().rstrip('/')
    model = config.model.strip() or "qwen2.5:3b"
    embed_model = config.embed_model.strip() or "bge-m3"

    settings.OLLAMA_HOST  = host
    settings.OLLAMA_PORT  = config.port
    settings.OLLAMA_MODEL = model
    settings.EMBED_MODEL  = embed_model

    # Persiste nel .env per sopravvivere ai restart
    env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
    env_path = os.path.normpath(env_path)
    try:
        if os.path.exists(env_path):
            content = open(env_path).read()
            if re.search(r"^OLLAMA_HOST=", content, re.MULTILINE):
                content = re.sub(r"^OLLAMA_HOST=.*$", f"OLLAMA_HOST={host}", content, flags=re.MULTILINE)
            else:
                content += f"\nOLLAMA_HOST={host}"
                
            if re.search(r"^OLLAMA_MODEL=", content, re.MULTILINE):
                content = re.sub(r"^OLLAMA_MODEL=.*$", f"OLLAMA_MODEL={model}", content, flags=re.MULTILINE)
            else:
                content += f"\nOLLAMA_MODEL={model}"

            if re.search(r"^SEMANTIC_EMBEDDING_MODEL=", content, re.MULTILINE):
                content = re.sub(r"^SEMANTIC_EMBEDDING_MODEL=.*$", f"SEMANTIC_EMBEDDING_MODEL={embed_model}", content, flags=re.MULTILINE)
            else:
                content += f"\nSEMANTIC_EMBEDDING_MODEL={embed_model}"
                
            open(env_path, "w").write(content)
            logger.info(f"Ollama host={host} model={model} persistito nel .env")
    except Exception as e:
        logger.warning(f"Impossibile scrivere nel .env: {e}")

    logger.info(f"Ollama host={host} model={model} embed={embed_model} persistito nel .env")
    return {"status": "ok", "host": host, "port": config.port, "model": model, "embed_model": embed_model}

@router.get("/api/settings/ollama")
def get_ollama_settings():
    """Ritorna le configurazioni attuali di Ollama."""
    return {
        "host":        settings.OLLAMA_HOST,
        "port":        settings.OLLAMA_PORT,
        "model":       getattr(settings, "OLLAMA_MODEL", "qwen2.5:3b"),
        "embed_model": getattr(settings, "EMBED_MODEL",  "bge-m3"),
        "ner_model":   os.getenv("NER_MODEL_NAME", "aendriu/bert-ner-italian-historical"),
    }
