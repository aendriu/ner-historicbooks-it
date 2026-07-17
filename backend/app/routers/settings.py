from fastapi import APIRouter
from pydantic import BaseModel
import logging
import os
import re
import requests

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


def _upsert_env_var(content: str, key: str, value: str) -> str:
    """Inserisce o aggiorna una variabile d'ambiente nel contenuto del file .env.

    Args:
        content: contenuto attuale del file .env.
        key: nome della variabile.
        value: nuovo valore.

    Returns:
        Contenuto aggiornato del file .env.
    """
    if re.search(rf"^{key}=", content, re.MULTILINE):
        return re.sub(rf"^{key}=.*$", f"{key}={value}", content, flags=re.MULTILINE)
    return content + f"\n{key}={value}"

class OllamaConfig(BaseModel):
    """Schema di validazione per la configurazione Ollama ricevuta dal frontend."""
    host: str
    port: str
    model: str = "qwen2.5:3b"
    embed_model: str = "bge-m3"

@router.post("/api/settings/ollama")
def update_ollama_settings(config: OllamaConfig):
    """Aggiorna la configurazione Ollama in memoria e persiste le modifiche nel file .env."""
    host = config.host.strip().rstrip('/')
    model = config.model.strip() or "qwen2.5:3b"
    embed_model = config.embed_model.strip() or "bge-m3"

    settings.OLLAMA_HOST         = host
    settings.OLLAMA_PORT         = config.port
    settings.OLLAMA_MODEL        = model
    settings.EMBED_MODEL         = embed_model

    # Persiste nel .env per sopravvivere ai restart
    env_path = os.path.join(os.path.dirname(__file__), "../../../.env")
    env_path = os.path.normpath(env_path)
    try:
        if os.path.exists(env_path):
            with open(env_path) as f:
                content = f.read()
            content = _upsert_env_var(content, "OLLAMA_HOST", host)
            content = _upsert_env_var(content, "OLLAMA_MODEL", model)
            content = _upsert_env_var(content, "SEMANTIC_EMBEDDING_MODEL", embed_model)
                
            with open(env_path, "w") as f:
                f.write(content)
            logger.info(f"Ollama host={host} model={model} persistito nel .env")
    except Exception as e:
        logger.warning(f"Impossibile scrivere nel .env: {e}")

    # Check installed models on Ollama
    installed_models = []
    missing_models = []
    base_url = host if host.startswith("http") else f"http://{host}:{config.port}"
    try:
        r = requests.get(f"{base_url}/api/tags", timeout=5)
        r.raise_for_status()
        data = r.json()
        installed_models = [m["name"] for m in data.get("models", [])]
        
        required_models = [model, embed_model]
        for req in required_models:
            # We do a loose check (e.g. if 'qwen3.5:9b' is in 'qwen3.5:9b:latest')
            if not any(req in m for m in installed_models):
                missing_models.append(req)
    except Exception as e:
        logger.warning(f"Impossibile verificare i modelli su Ollama: {e}")

    return {
        "status": "ok", 
        "host": host, 
        "port": config.port,
        "model": model, 
        "embed_model": embed_model,
        "missing_models": missing_models,
        "installed_models": installed_models
    }

@router.get("/api/settings/ollama")
def get_ollama_settings():
    """Restituisce la configurazione corrente di Ollama."""
    return {
        "host":         settings.OLLAMA_HOST,
        "port":         settings.OLLAMA_PORT,
        "model":        getattr(settings, "OLLAMA_MODEL",        "qwen2.5:3b"),
        "embed_model":  getattr(settings, "EMBED_MODEL",         "bge-m3"),
        "ner_model":    os.getenv("NER_MODEL_NAME", "aendriu/bert-ner-italian-historical"),
    }
