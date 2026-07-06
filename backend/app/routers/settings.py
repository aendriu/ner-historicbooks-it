from fastapi import APIRouter
from pydantic import BaseModel
import requests
import logging

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])

class OllamaConfig(BaseModel):
    host: str
    port: str

@router.post("/api/settings/ollama")
def update_ollama_settings(config: OllamaConfig):
    """
    Tenta di pingare il server Ollama specificato.
    Se risponde, aggiorna i setting globali. Altrimenti ritorna un errore.
    """
    base_url = config.host.rstrip('/')
    if not base_url.startswith("http"):
        base_url = f"http://{base_url}:{config.port}"
        
    try:
        # Check connection with a fast timeout
        response = requests.get(f"{base_url}/api/tags", timeout=5)
        response.raise_for_status()
        
        # Valid connection, update global settings
        settings.OLLAMA_HOST = config.host
        settings.OLLAMA_PORT = config.port
        
        logger.info(f"Ollama server updated to: {base_url}")
        return {"status": "ok", "host": settings.OLLAMA_HOST, "port": settings.OLLAMA_PORT}
        
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to connect to Ollama at {base_url}: {e}")
        return {"status": "error", "message": "Impossibile raggiungere il server Ollama a questo indirizzo."}

@router.get("/api/settings/ollama")
def get_ollama_settings():
    """Ritorna le configurazioni attuali di Ollama."""
    return {"host": settings.OLLAMA_HOST, "port": settings.OLLAMA_PORT}
