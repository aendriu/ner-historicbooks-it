"""Client centralizzato per le chiamate all'API Ollama.

Raggruppa in un'unica classe la logica di connessione, generazione
testo e calcolo embedding, eliminando la duplicazione presente
in summarizer.py, ocr.py e chunker.py.
"""

import json
import logging
import re

import numpy as np
import requests

from app.config import settings

logger = logging.getLogger(__name__)


def _strip_thinking(text: str) -> str:
    """Rimuove i blocchi <think>...</think> generati da modelli Qwen3 in thinking mode.

    Args:
        text: testo grezzo della risposta Ollama.

    Returns:
        Testo ripulito dai blocchi di ragionamento interno.
    """
    return re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()


class OllamaClient:
    """Client per interagire con l'API Ollama.

    Centralizza la costruzione dell'URL base, le chiamate di generazione
    testo (con e senza streaming) e il calcolo degli embedding.
    I parametri di connessione vengono letti dall'oggetto settings
    globale ad ogni chiamata, così da riflettere eventuali modifiche
    a runtime (es. cambio host dal frontend).
    """

    def __init__(self):
        """Inizializza il client Ollama (nessuna connessione aperta)."""
        pass

    def get_base_url(self) -> str:
        """Costruisce l'URL base del server Ollama dalla configurazione corrente.

        Returns:
            URL base senza slash finale (es. 'http://localhost:11434').
        """
        return settings.get_base_url()

    def generate(
        self,
        prompt: str,
        *,
        model: str | None = None,
        temperature: float = 0.3,
        num_ctx: int = 8192,
        num_predict: int = 2048,
        timeout: int = 300,
        think: bool = False,
    ) -> str:
        """Genera testo tramite l'API Ollama con streaming.

        Args:
            prompt: il prompt da inviare al modello.
            model: nome del modello (default: settings.OLLAMA_MODEL).
            temperature: temperatura di campionamento.
            num_ctx: dimensione del contesto in token.
            num_predict: numero massimo di token generati.
            timeout: timeout della richiesta HTTP in secondi.
            think: se True, abilita il thinking mode di Qwen3.

        Returns:
            Testo generato, ripulito dai blocchi di thinking.
        """
        url = f"{self.get_base_url()}/api/generate"
        use_model = model or settings.OLLAMA_MODEL

        try:
            r = requests.post(
                url,
                json={
                    "model": use_model,
                    "prompt": prompt,
                    "stream": True,
                    "think": think,
                    "options": {
                        "temperature": temperature,
                        "num_ctx": num_ctx,
                        "num_predict": num_predict,
                    },
                },
                stream=True,
                timeout=timeout,
            )
            r.raise_for_status()
            parts = []
            for line in r.iter_lines():
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                    parts.append(chunk.get("response", ""))
                    if chunk.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
            raw = "".join(parts)
            result = _strip_thinking(raw)
            if not result:
                preview = raw[:300].replace("\n", "↵") if raw else "<STRINGA VUOTA>"
                logger.warning(f"Risposta vuota dopo strip. Raw preview: {preview}")
            return result
        except Exception as e:
            logger.error(f"Errore chiamata Ollama (generate): {e}")
            return ""

    def generate_long(
        self,
        prompt: str,
        *,
        model: str | None = None,
        timeout: int = 600,
    ) -> str:
        """Genera testo con contesto e output estesi per il riassunto globale (Livello 0).

            model: nome del modello (default: OLLAMA_MODEL).
            timeout: timeout della richiesta HTTP in secondi.

        Returns:
            Testo generato, ripulito dai blocchi di thinking.
        """
        if model is None:
            model = settings.OLLAMA_MODEL

        return self.generate(
            prompt,
            model=model,
            temperature=0.2,
            num_ctx=32_768,
            num_predict=8192,
            timeout=timeout,
            think=False,
        )

    def embed(self, text: str, *, model: str | None = None) -> list[float]:
        """Calcola l'embedding di un singolo testo tramite Ollama.

        Args:
            text: il testo da vettorializzare.
            model: nome del modello di embedding (default: settings.EMBED_MODEL).

        Returns:
            Lista di float rappresentante l'embedding.

        Raises:
            RuntimeError: se la chiamata all'API fallisce.
        """
        url = f"{self.get_base_url()}/api/embed"
        use_model = model or settings.EMBED_MODEL

        try:
            r = requests.post(
                url,
                json={"model": use_model, "input": [text]},
                timeout=120,
            )
            r.raise_for_status()
            embeddings = r.json()["embeddings"]
            return embeddings[0]
        except Exception as e:
            raise RuntimeError(f"Ollama embedding fallito ({use_model}): {e}") from e

    def embed_batch(
        self, texts: list[str], *, model: str | None = None
    ) -> "np.ndarray":
        """Calcola gli embedding per una lista di testi.

        Args:
            texts: lista di testi da vettorializzare.
            model: nome del modello di embedding (default: settings.EMBED_MODEL).

        Returns:
            Array numpy con gli embedding (shape: len(texts) x dim).

        Raises:
            RuntimeError: se la chiamata all'API fallisce.
        """
        url = f"{self.get_base_url()}/api/embed"
        use_model = model or settings.EMBED_MODEL

        try:
            r = requests.post(
                url,
                json={"model": use_model, "input": texts},
                timeout=120,
            )
            r.raise_for_status()
            embeddings = r.json()["embeddings"]
            return np.array(embeddings, dtype=np.float32)
        except Exception as e:
            raise RuntimeError(f"Ollama embedding batch fallito ({use_model}): {e}") from e


# Istanza singleton per uso globale
ollama_client = OllamaClient()
