import os
import json
import logging
import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Client AWS per Bedrock (locale)
bedrock = boto3.client("bedrock-runtime", region_name="eu-central-1")

# Costanti
MODEL_ID = 'eu.anthropic.claude-haiku-4-5-20251001-v1:0'

def generate_chapter_summary(chapter_title: str, chunks_data: list) -> str:
    """
    Invia i chunk del capitolo all'LLM e restituisce il riassunto narrativo.
    `chunks_data` è una lista di dict: [{"text": "...", "topic_hint": "...", "entities": [...]}]
    """
    if not chunks_data:
        return ""

    # Preparazione del testo da inviare
    combined_text = "\n\n".join([f"--- [Frammento: {c.get('topic_hint', 'N/A')}] ---\n{c.get('text', '')}" for c in chunks_data])

    prompt = f"""Sei un esperto riassuntore di testi letterari e storici. 
Ti sto fornendo i contenuti del capitolo intitolato "{chapter_title}".
Il testo è stato diviso in frammenti semantici, ognuno con un suggerimento di argomento (topic hint).

ISTRUZIONI:
- Scrivi un riassunto coeso e discorsivo di questo capitolo.
- Cattura gli eventi chiave, le motivazioni dei personaggi e i luoghi principali.
- Il tono deve essere neutro, narrativo e professionale.
- Non fare riferimenti al fatto che il testo ti è stato fornito a frammenti (es. "Nel primo frammento...").
- Mantieni una lunghezza adeguata (circa 2-4 paragrafi).

TESTO DEL CAPITOLO:
{combined_text}

Restituisci SOLO il testo del riassunto, senza premesse o conclusioni.
"""

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1500,
        "temperature": 0.3,
        "messages": [
            {"role": "user", "content": prompt}
        ]
    }

    try:
        response = bedrock.invoke_model(
            body=json.dumps(payload),
            modelId=MODEL_ID,
            accept="application/json",
            contentType="application/json",
        )
        response_body = json.loads(response.get("body").read())
        
        if "content" in response_body and len(response_body["content"]) > 0:
            summary_text = response_body["content"][0].get("text", "").strip()
            return summary_text
        else:
            logger.warning(f"Risposta imprevista da Bedrock per il riassunto: {response_body}")
            return ""

    except Exception as e:
        logger.error(f"Errore durante la generazione del riassunto: {str(e)}")
        return "Errore nella generazione del riassunto."
