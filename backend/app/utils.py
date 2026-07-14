"""Utilità condivise per l'applicazione.

Funzioni helper riutilizzate in più moduli per evitare
duplicazione di logica comune.
"""

from datetime import datetime, timezone


def extract_text_content(data: dict) -> str:
    """Estrae il contenuto testuale da un dizionario JSON.

    Cerca il testo usando le chiavi 'contenuto', 'text' o 'content'
    in ordine di priorità (formato standard dei file del progetto).

    Args:
        data: dizionario con i dati del documento.

    Returns:
        Il testo estratto, oppure stringa vuota se non trovato.
    """
    return data.get("contenuto", data.get("text", data.get("content", "")))


def utcnow_iso() -> str:
    """Restituisce il timestamp UTC corrente in formato ISO 8601.

    Usa datetime.now(timezone.utc) al posto del deprecato
    datetime.utcnow() per evitare warning nelle versioni
    recenti di Python.

    Returns:
        Stringa ISO 8601 con timezone UTC.
    """
    return datetime.now(timezone.utc).isoformat()
