import json
import logging
import os
import re
import time
import traceback
from pathlib import Path

from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

from app.config import settings

logger = logging.getLogger(__name__)
from .ner_chunking import make_chunks

# ====== CONFIG ======
MODEL_NAME: str = getattr(settings, "NER_MODEL_NAME", "aendriu/bert-ner-italian-historical")
MAX_INPUT_CHARS: int = 2000
OVERLAP_CHARS: int = 300
ALLOWED_LABELS: set[str] = {"PER", "LOC", "ORG", "WORK", "DATE", "EVENT", "TIT", "REL", "FANT"}
SCORE_THRESHOLD: float = float(os.getenv("NER_SCORE_THRESHOLD", "0.65"))
MIN_ENTITY_CHARS: int = int(os.getenv("NER_MIN_ENTITY_CHARS", "3"))

DATE_RE = re.compile(r"^(\d{3,4}|\d{1,2}\s+[a-zà-ù]+\s+\d{3,4}|[ivxlcdm]{1,7})$", re.IGNORECASE)
STOPWORD_RE = re.compile(
    r"^(il|lo|la|i|gli|le|un|uno|una|di|de|del|dello|della|dei|degli|delle|e|o|a|da|in|su|con|per|tra|fra|l|d)$",
    re.IGNORECASE,
)

# Blacklist rimossa per favorire un approccio "post-process" futuro

def _normalize_label(label: str) -> str | None:
    """Normalizza l'etichetta NER rimuovendo i prefissi BIO e filtrando MISC."""
    label = label.replace("B-", "").replace("I-", "").upper()
    if label == "MISC":
        return None
    return label if label in ALLOWED_LABELS else None

# Inizializzazione pigra della pipeline
_ner_pipeline = None

def get_ner_pipeline():
    """Restituisce la pipeline NER HuggingFace, inizializzandola pigramente alla prima chiamata."""
    global _ner_pipeline
    if _ner_pipeline is None:
        logger.info(f"Caricamento modello HuggingFace: {MODEL_NAME}")
        tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModelForTokenClassification.from_pretrained(MODEL_NAME)
        _ner_pipeline = pipeline(
            "token-classification",
            model=model,
            tokenizer=tokenizer,
            aggregation_strategy="simple",
            device=-1,
        )
    return _ner_pipeline


def _clean_span(span: str) -> str:
    """Ripulisce uno span di testo rimuovendo spazi e punteggiatura ai bordi."""
    span = span.strip()
    span = span.strip("'’\"“”‘’()[]{}.,;:!?-")
    span = re.sub(r"\s+", " ", span)
    return span

_BOUNDARY_RE = re.compile(r"[\s\'\'\"\"\"\'\'\(\)\[\]\{\}\.\,\;\:\!\?\-\–\—\/\\]")

def _snap_offsets(text: str, start: int, end: int, max_expand: int = 2) -> tuple[int, int]:
    """Espande gli offset di un'entità fino al confine di parola più vicino."""
    n = len(text)
    orig_start, orig_end = start, end
    while start > 0 and (orig_start - start) < max_expand and not _BOUNDARY_RE.match(text[start - 1]):
        start -= 1
    while start < end and (start - orig_start) < max_expand and _BOUNDARY_RE.match(text[start]):
        start += 1
    while end < n and (end - orig_end) < max_expand and not _BOUNDARY_RE.match(text[end]):
        end += 1
    while end > start and (orig_end - end) < max_expand and _BOUNDARY_RE.match(text[end - 1]):
        end -= 1
    return start, end

def _trim_offsets_to_token(text: str, start: int, end: int) -> tuple[int, int]:
    """Restringe gli offset eliminando separatori ai bordi dello span."""
    while start < end and _BOUNDARY_RE.match(text[start]):
        start += 1
    while end > start and _BOUNDARY_RE.match(text[end - 1]):
        end -= 1
    return start, end

def _valid_entity(label: str, text: str, score: float) -> bool:
    """Verifica se un'entità è valida in base a soglia, lunghezza e contenuto."""
    if score < SCORE_THRESHOLD:
        return False
    text = _clean_span(text)
    if not text:
        return False
    if label != "DATE" and len(text) < MIN_ENTITY_CHARS:
        return False
    alpha_ratio = sum(ch.isalpha() for ch in text) / max(1, len(text))
    if label != "DATE" and alpha_ratio < 0.6:
        return False
    if label == "DATE":
        if not DATE_RE.match(text) and score < 0.85:
            return False
    elif STOPWORD_RE.match(text):
        return False



    if label == "PER" and not any(c.isupper() for c in text):
        return False
    if label == "FANT" and score < max(SCORE_THRESHOLD, 0.75):
        return False
    if label == "TIT" and len(text) < 2:
        return False
    return True

def process_chunk(ner, chunk_text: str, chunk_start_offset: int) -> list:
    """Estrae le entità NER dal chunk, ricalcolando gli offset rispetto al testo globale."""
    text = chunk_text[:MAX_INPUT_CHARS]
    preds = ner(text)

    raw_entities = []
    for ent in preds:
        label = _normalize_label(ent.get("entity_group", ent.get("entity", "")))
        if not label:
            continue

        start = int(ent.get("start", 0))
        end = int(ent.get("end", 0))
        span = text[start:end]
        score = float(ent.get("score", 0.0))

        if not span or not _valid_entity(label, span, score):
            continue

        new_start, new_end = _snap_offsets(text, start, end)
        new_start, new_end = _trim_offsets_to_token(text, new_start, new_end)
        cleaned = _clean_span(text[new_start:new_end])

        if not cleaned:
            continue

        raw_entities.append({
            "label": label,
            "text": cleaned,
            "start_char": new_start,
            "end_char": new_end,
            "score": score,
        })

    # Merge adiacenti
    raw_entities.sort(key=lambda x: (x["start_char"], x["end_char"]))
    merged = []
    for ent in raw_entities:
        if not merged:
            merged.append(ent)
            continue

        prev = merged[-1]
        if ent["label"] == prev["label"] and ent["start_char"] <= prev["end_char"] + 1:
            prev["end_char"] = max(prev["end_char"], ent["end_char"])
            prev["text"] = text[prev["start_char"]:prev["end_char"]]
            prev["score"] = max(prev["score"], ent["score"])
        else:
            merged.append(ent)

    entities = []
    for ent in merged:
        start, end = _trim_offsets_to_token(text, ent["start_char"], ent["end_char"])
        if start >= end:
            continue
        clean_text = _clean_span(text[start:end])
        if not clean_text or not _valid_entity(ent["label"], clean_text, ent["score"]):
            continue
            
        entities.append({
            "label": ent["label"],
            "word": clean_text,
            "score": round(ent["score"], 4),
            # Ricalcola in base al file globale
            "start": chunk_start_offset + start,
            "end": chunk_start_offset + end,
        })

    return entities

def extract_ner_from_file(clean_file_path: str, output_json_path: str, progress_cb=None) -> bool:
    """Legge il JSON pulito, esegue il NER a chunk e salva le entità trovate.

    Args:
        clean_file_path: percorso del file JSON pulito.
        output_json_path: percorso di output per le entità.
        progress_cb: callback opzionale per il progresso.

    Returns:
        True se l'estrazione ha avuto successo, False altrimenti.
    """
    try:
        with open(clean_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        text = data.get('contenuto', data.get('text', ''))
        book_name = Path(clean_file_path).stem
        
        if not text.strip():
            logger.warning(f"Testo vuoto per {clean_file_path}")
            return False

        # Creiamo i chunk fittizi solo per permettere al modello di ingerirli
        chunks = make_chunks(text, max_chars=MAX_INPUT_CHARS, overlap_chars=OVERLAP_CHARS)
        
        if progress_cb:
            progress_cb(0, len(chunks), "Download/Caricamento modello BERT in corso (potrebbe richiedere 1-2 minuti la prima volta)...")
        
        ner = get_ner_pipeline()
        
        all_entities = []
        for i, c in enumerate(chunks):
            # c.start è l'offset nel testo globale
            ents = process_chunk(ner, c.text, c.start)
            all_entities.extend(ents)
            if progress_cb:
                progress_cb(i + 1, len(chunks), len(ents))
            
        # Rimuoviamo duplicati esatti dovuti all'overlap dei chunk
        unique_entities = { (e["start"], e["end"], e["label"]): e for e in all_entities }.values()
        sorted_entities = sorted(list(unique_entities), key=lambda x: x["start"])

        output_data = {
            "book_name": book_name,
            "total_entities": len(sorted_entities),
            "entities": sorted_entities
        }
        
        with open(output_json_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
            
        return True

    except Exception as e:
        logger.error(f"Errore durante l'estrazione NER: {e}\n{traceback.format_exc()}")
        return False
