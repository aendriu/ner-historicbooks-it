import os
import json
import logging
import requests
import textwrap

logger = logging.getLogger(__name__)

# Configurable via environment variable (default for local, but in docker-compose will be 'ollama')
from app.config import OLLAMA_HOST, OLLAMA_PORT, OLLAMA_MODEL, DATA_DIR
import traceback

def chunk_text(text: str, max_chunk_size: int = 1500) -> list:
    """
    Splits text into chunks of roughly max_chunk_size characters,
    trying to split at paragraph or sentence boundaries.
    """
    paragraphs = text.split("\n")
    chunks = []
    current_chunk = ""
    
    for p in paragraphs:
        if len(current_chunk) + len(p) < max_chunk_size:
            current_chunk += p + "\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            
            # If a single paragraph is still too long, use textwrap
            if len(p) >= max_chunk_size:
                sub_chunks = textwrap.wrap(p, width=max_chunk_size, break_long_words=False)
                for sc in sub_chunks[:-1]:
                    chunks.append(sc)
                current_chunk = sub_chunks[-1] + "\n" if sub_chunks else ""
            else:
                current_chunk = p + "\n"
                
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks

def call_ollama(text_chunk: str) -> str:
    """
    Calls the local Ollama API to clean the text chunk.
    """
    if OLLAMA_HOST.startswith("http://") or OLLAMA_HOST.startswith("https://"):
        url = f"{OLLAMA_HOST.rstrip('/')}/api/generate"
    else:
        url = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}/api/generate"
    system_prompt = (
        "Sei un assistente specializzato in filologia e restauro di testi in italiano antico. "
        "Il tuo compito è pulire gli errori di OCR (riconoscimento ottico dei caratteri). "
        "Analizza il testo fornito, trova gli errori (es. capolettera staccati come 'L udovico', simboli estranei) e restituisci "
        "ESCLUSIVAMENTE un array JSON con le correzioni necessarie.\n"
        "Ogni oggetto nell'array deve avere due chiavi:\n"
        "- 'errato': la frase originale contenente l'errore (includi ALMENO 3-4 parole di contesto prima e dopo l'errore per univocità).\n"
        "- 'corretto': la stessa frase con l'errore corretto.\n"
        "Esempio:\n"
        '[{"errato": "disse il paladin o riandò verso", "corretto": "disse il paladino Orlando verso"}]\n'
        "NON scrivere nient'altro fuori dal JSON. Se non ci sono errori, restituisci []."
    )
    
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": f"{system_prompt}\n\nTESTO DA CORREGGERE:\n{text_chunk}\n\nRISPOSTA JSON:",
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.0, # Greedy decoding (always picks the highest probability token)
            "seed": 42,         # Fixed seed for pseudo-random number generation tie-breakers
            "num_predict": 1024
        }
    }
    
    try:
        response = requests.post(url, json=payload, timeout=600)
        response.raise_for_status()
        result = response.json()
        return result.get("response", "[]").strip()
    except requests.exceptions.RequestException as e:
        logger.error(f"Errore di comunicazione con Ollama: {e}")
        # Se c'è un errore, per sicurezza restituiamo il chunk originale (vuoto array)
        return "[]"

def run_llm_cleaner(input_path: str, output_path: str, progress_cb=None) -> bool:
    """
    Legge il file JSON grezzo, usa Ollama per pulire il testo a pezzi, 
    e salva il risultato.
    """
    logger.info(f"Avvio LLM Cleaner (Ollama {OLLAMA_MODEL}) su: {input_path}")
    
    if not os.path.exists(input_path):
        logger.error(f"File non trovato: {input_path}")
        return False
        
    if OLLAMA_HOST.startswith("http://") or OLLAMA_HOST.startswith("https://"):
        base_url = OLLAMA_HOST.rstrip('/')
    else:
        base_url = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

    # Controllo preventivo: se Ollama non risponde, abortiamo subito
    try:
        requests.get(f"{base_url}/api/tags", timeout=5)
    except requests.exceptions.RequestException:
        logger.error(f"Ollama non raggiungibile all'indirizzo {base_url}. Salto l'intera fase LLM.")
        return False
        
    filename = os.path.basename(input_path)
    filename_no_ext = os.path.splitext(filename)[0]
    
    tmp_dir = os.path.join(DATA_DIR, "tmp_ollama", filename_no_ext)
    os.makedirs(tmp_dir, exist_ok=True)
    
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                contenuto = data.get("contenuto", data.get("text", data.get("content", "")))
            except json.JSONDecodeError:
                f.seek(0)
                contenuto = f.read()
                data = {"contenuto": contenuto}
                
        if not contenuto.strip():
            logger.warning("Il file caricato è vuoto o non contiene testo valido.")
            return False
            
        chunks = chunk_text(contenuto)
        cleaned_chunks = []
        
        logger.info(f"Testo diviso in {len(chunks)} chunks. Inizio elaborazione Ollama...")
        if progress_cb:
            progress_cb(0, len(chunks), "Inizio ricerca errori LLM (Modalità JSON)...")
        
        for i, chunk in enumerate(chunks):
            logger.info(f"Elaborazione chunk {i+1}/{len(chunks)}...")
            if progress_cb:
                progress_cb(i + 1, len(chunks), f"Analisi errori chunk {i+1}/{len(chunks)}")
            
            json_str = call_ollama(chunk)
            
            # Salva il file temporaneo
            tmp_file = os.path.join(tmp_dir, f"chunk_{i:03d}.json")
            
            corrections = []
            try:
                if json_str:
                    corrections = json.loads(json_str)
                    if not isinstance(corrections, list):
                        corrections = []
            except json.JSONDecodeError:
                logger.warning(f"Ollama non ha restituito un JSON valido per il chunk {i}")
            
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump({"original": chunk, "corrections": corrections, "raw_response": json_str}, f, ensure_ascii=False, indent=2)
                
            # Applica le correzioni
            current_cleaned = chunk
            for c in corrections:
                errato = c.get("errato")
                corretto = c.get("corretto")
                if errato and corretto and errato in current_cleaned:
                    current_cleaned = current_cleaned.replace(errato, corretto)
                    
            cleaned_chunks.append(current_cleaned)
            
        # Riassembla il testo
        cleaned_text = "\n\n".join(cleaned_chunks)
        
        data["contenuto"] = cleaned_text
        
        # Assicurati che la cartella di output esista
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            
        logger.info(f"Pulizia LLM completata. Salvato in: {output_path}")
        return True
        
    except Exception as e:
        logger.error(f"Errore durante l'esecuzione dell'LLM cleaner: {e}\n{traceback.format_exc()}")
        return False
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
