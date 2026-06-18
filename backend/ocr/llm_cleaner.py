import json
import os
import boto3
from typing import Callable, Optional

# Costanti
MODEL_ID = "global.anthropic.claude-haiku-4-5-20251001-v1:0"
TARGET_CHUNK_CHARS = 4000  # Dimensione ideale del chunk (in caratteri)
MAX_CHUNK_CHARS = 6000

bedrock = boto3.client("bedrock-runtime", region_name="eu-central-1")

SYSTEM_PROMPT = """Sei un esperto restauratore di testi storici italiani digitalizzati.
Il tuo compito è correggere unicamente gli errori tipografici introdotti da un processo di scansione OCR imperfetto.

REGOLE TASSATIVE:
1. NON riassumere, NON abbreviare, NON omettere alcuna parte del testo.
2. NON modernizzare il linguaggio: se una parola è scritta in italiano antico o desueto, lasciala com'è, a meno che non sia palesemente un errore di OCR (es. "l'1talia" -> "l'Italia").
3. Correggi simboli casuali, caratteri errati, spaziature anomale, apostrofi o virgolette spezzate.
4. Restituisci SOLO ed ESCLUSIVAMENTE il testo corretto, senza alcuna introduzione, senza note, senza spiegazioni. Nessun preambolo. Non aggiungere "Ecco il testo:".
"""

def split_into_chunks(text: str, target_size: int = TARGET_CHUNK_CHARS) -> list[str]:
    """Divide il testo in chunk, cercando di tagliare su doppio a capo, poi singolo, poi spazio."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + target_size, len(text))
        if end < len(text):
            # Cerca di tagliare su doppio a capo
            cut_pos = text.rfind('\n\n', start, end)
            if cut_pos <= start:
                # Fallback su singolo a capo
                cut_pos = text.rfind('\n', start, end)
            if cut_pos <= start:
                # Fallback su punto
                cut_pos = text.rfind('. ', start, end)
            if cut_pos <= start:
                # Fallback su spazio
                cut_pos = text.rfind(' ', start, end)
                
            if cut_pos > start:
                end = cut_pos + 1 # Include il carattere di taglio (es. spazio o newline)
                
        chunk = text[start:end]
        chunks.append(chunk)
        start = end
        
    return chunks

import time

def call_bedrock_cleaner(chunk_text: str, max_retries: int = 5) -> str:
    """Invia un chunk all'LLM e restituisce il testo pulito, gestendo il throttling."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 4096,
        "system": SYSTEM_PROMPT,
        "temperature": 0.0,
        "messages": [{"role": "user", "content": chunk_text}],
    })
    
    base_delay = 2.0
    for attempt in range(max_retries):
        try:
            response = bedrock.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            result = json.loads(response["body"].read())
            cleaned_text = result["content"][0]["text"]
            return cleaned_text
        except Exception as e:
            error_msg = str(e)
            if "ThrottlingException" in error_msg or "TooManyRequests" in error_msg or "Rate exceeded" in error_msg:
                delay = base_delay * (2 ** attempt)
                print(f"Throttling rilevato (tentativo {attempt+1}/{max_retries}). Attesa di {delay}s...")
                time.sleep(delay)
            elif "Connection" in error_msg or "Endpoint" in error_msg or "timeout" in error_msg.lower():
                delay = base_delay * (2 ** attempt)
                print(f"Errore di rete rilevato (tentativo {attempt+1}/{max_retries}). Attesa di {delay}s...")
                time.sleep(delay)
            else:
                print(f"Errore Bedrock OCR non recuperabile: {e}")
                raise e # Errore grave (es. credenziali errate o prompt invalido)
                
    print("Superato il numero massimo di tentativi. Impossibile contattare Bedrock.")
    raise Exception("Impossibile completare la pulizia a causa di errori continui di rete/throttling.")

def run_llm_cleaner(input_path: str, output_path: str, progress_cb: Optional[Callable[[int, int, str], None]] = None) -> bool:
    """Legge il raw_path, fa chunking, chiama l'LLM per pulire, e salva."""
    
    # Leggi il testo originale
    raw_text = ""
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            if input_path.endswith(".json"):
                data = json.load(f)
                raw_text = data.get("contenuto", data.get("text", data.get("content", "")))
            else:
                raw_text = f.read()
    except Exception as e:
        print(f"Errore lettura {input_path}: {e}")
        return False

    if not raw_text.strip():
        print("Testo grezzo vuoto.")
        return False
        
    chunks = split_into_chunks(raw_text)
    total_chunks = len(chunks)
    
    if progress_cb:
        progress_cb(0, total_chunks, f"Suddiviso in {total_chunks} chunk. Avvio LLM...")

    cleaned_chunks = []
    
    for i, chunk in enumerate(chunks):
        if progress_cb:
            progress_cb(i + 1, total_chunks, f"Pulizia chunk {i+1}/{total_chunks} in corso...")
            
        cleaned_chunk = call_bedrock_cleaner(chunk)
        cleaned_chunks.append(cleaned_chunk)
        
    final_text = "".join(cleaned_chunks)
    
    # Salva il risultato
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        # Salviamo sempre come JSON con chiave "contenuto" per mantenere retrocompatibilità
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump({"contenuto": final_text}, f, ensure_ascii=False, indent=2)
        if progress_cb:
            progress_cb(total_chunks, total_chunks, "Salvataggio completato con successo!")
        return True
    except Exception as e:
        print(f"Errore salvataggio {output_path}: {e}")
        return False

