import os
import json
import logging
import re
from datetime import datetime
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

# Configurazione del boss!
MAX_CHUNK_CHARS = 2000
OVERLAP_CHARS = 300
SIMILARITY_THRESHOLD = 0.5  # Soglia sotto la quale consideriamo un cambio semantico

_model = None

def get_embedding_model():
    global _model
    if _model is None:
        logger.info("Caricamento modello SentenceTransformer: paraphrase-multilingual-MiniLM-L12-v2")
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _model

def split_into_paragraphs(text):
    # Divide il testo in paragrafi
    paras = re.split(r'\n\s*\n', text)
    result = []
    current_char = 0
    for p in paras:
        p = p.strip()
        if not p:
            current_char += len(p) + 2
            continue
        
        start = text.find(p, current_char)
        if start == -1:
            start = current_char
        end = start + len(p)
        
        result.append({
            "text": p,
            "char_start": start,
            "char_end": end
        })
        current_char = end
    return result

def find_semantic_boundaries(paragraphs):
    if len(paragraphs) < 3:
        return []

    model = get_embedding_model()
    texts = [p["text"] for p in paragraphs]
    embeddings = model.encode(texts)
    
    similarities = []
    for i in range(len(embeddings) - 1):
        sim = cosine_similarity([embeddings[i]], [embeddings[i+1]])[0][0]
        similarities.append(sim)
        
    boundaries = []
    for i, sim in enumerate(similarities):
        # Se c'è un crollo di similarità, è un boundary
        if sim < SIMILARITY_THRESHOLD:
            boundaries.append(i + 1)
            
    return boundaries

def find_explicit_chapters(paragraphs):
    boundaries = []
    pattern = re.compile(r'^(CAPITOLO|CAPO|CAP\.|LIBRO|PARTE)\s+([IVXLCDM]+|\d+)', re.IGNORECASE)
    for i, p in enumerate(paragraphs):
        if pattern.search(p["text"]):
            boundaries.append(i)
    return boundaries

def split_text_with_overlap(text, max_size, overlap):
    """Spezza una stringa lunga in chunk di max_size con overlap."""
    words = text.split()
    chunks = []
    current_words = []
    current_len = 0
    
    i = 0
    while i < len(words):
        w = words[i]
        if current_len + len(w) + 1 > max_size and current_words:
            # Salva il chunk
            chunk_str = " ".join(current_words)
            chunks.append(chunk_str)
            
            # Torna indietro per l'overlap
            overlap_len = 0
            back_idx = i - 1
            overlap_words = []
            while back_idx >= 0:
                overlap_len += len(words[back_idx]) + 1
                if overlap_len > overlap:
                    break
                overlap_words.insert(0, words[back_idx])
                back_idx -= 1
                
            current_words = overlap_words
            current_len = sum(len(x)+1 for x in current_words)
        
        current_words.append(w)
        current_len += len(w) + 1
        i += 1
        
    if current_words:
        chunks.append(" ".join(current_words))
        
    return chunks

def build_final_chunks(book_name, text, paragraphs, boundaries, entities):
    # Ordina e deduplica i boundaries
    boundaries = sorted(list(set(boundaries)))
    if 0 not in boundaries:
        boundaries.insert(0, 0)
    if len(paragraphs) not in boundaries:
        boundaries.append(len(paragraphs))
        
    final_chunks = []
    chunk_id = 1
    
    for i in range(len(boundaries) - 1):
        start_idx = boundaries[i]
        end_idx = boundaries[i+1]
        
        # Testo della sezione semantica
        section_paras = paragraphs[start_idx:end_idx]
        if not section_paras:
            continue
            
        section_start = section_paras[0]["char_start"]
        section_end = section_paras[-1]["char_end"]
        section_text = text[section_start:section_end]
        
        # Se la sezione supera il MAX_CHUNK_CHARS, la spezziamo forzatamente
        if len(section_text) > MAX_CHUNK_CHARS:
            sub_chunks = split_text_with_overlap(section_text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
            
            curr_start = section_start
            for sc in sub_chunks:
                sc_start = text.find(sc[:50], curr_start)
                if sc_start == -1:
                    sc_start = curr_start
                sc_end = sc_start + len(sc)
                
                # Trova entità in questo sub-chunk
                chunk_ents = [e for e in entities if e["start"] >= sc_start and e["end"] <= sc_end]
                
                final_chunks.append({
                    "book_name": book_name,
                    "chunk_id": chunk_id,
                    "text": sc,
                    "char_start": sc_start,
                    "char_end": sc_end,
                    "topic_hint": f"Sezione Semantica {i+1} (parte)",
                    "entities": chunk_ents,
                    "num_entities": len(chunk_ents)
                })
                chunk_id += 1
                # Avanza curr_start tenendo conto dell'overlap
                curr_start = sc_end - OVERLAP_CHARS - 100 
                if curr_start < sc_start: curr_start = sc_start
        else:
            chunk_ents = [e for e in entities if e["start"] >= section_start and e["end"] <= section_end]
            final_chunks.append({
                "book_name": book_name,
                "chunk_id": chunk_id,
                "text": section_text,
                "char_start": section_start,
                "char_end": section_end,
                "topic_hint": f"Sezione Semantica {i+1}",
                "entities": chunk_ents,
                "num_entities": len(chunk_ents)
            })
            chunk_id += 1
            
    # Assegna total_chunks
    for c in final_chunks:
        c["total_chunks"] = len(final_chunks)
        
    return final_chunks

def run_semantic_chunker(book_name, clean_file_path, ner_file_path, output_dir, progress_cb=None):
    """
    Esegue il chunking semantico vettoriale (locale).
    """
    try:
        if progress_cb: progress_cb(0, 4, "Caricamento testi...")
        with open(clean_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            text = data.get("contenuto", data.get("text", data.get("content", "")))
            
        with open(ner_file_path, "r", encoding="utf-8") as f:
            ner_data = json.load(f)
            entities = ner_data.get("entities", [])
            
        if progress_cb: progress_cb(1, 4, "Calcolo embedding e boundaries...")
        paragraphs = split_into_paragraphs(text)
        
        sem_boundaries = find_semantic_boundaries(paragraphs)
        exp_boundaries = find_explicit_chapters(paragraphs)
        
        all_boundaries = sem_boundaries + exp_boundaries
        
        if progress_cb: progress_cb(2, 4, f"Creazione chunk (max {MAX_CHUNK_CHARS}, overlap {OVERLAP_CHARS})...")
        chunks = build_final_chunks(book_name, text, paragraphs, all_boundaries, entities)
        
        if progress_cb: progress_cb(3, 4, "Salvataggio risultati...")
        book_out_dir = os.path.join(output_dir, book_name)
        os.makedirs(book_out_dir, exist_ok=True)
        
        manifest_chunks = []
        
        for c in chunks:
            c_file = os.path.join(book_out_dir, f"chunk_{c['chunk_id']:03d}.json")
            with open(c_file, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
                
            manifest_chunks.append({
                "chunk_id": c["chunk_id"],
                "topic_hint": c["topic_hint"],
                "char_start": c["char_start"],
                "char_end": c["char_end"],
                "num_entities": c["num_entities"],
                "text_length": len(c["text"])
            })
            
        manifest = {
            "book_name": book_name,
            "total_chunks": len(chunks),
            "created_at": datetime.utcnow().isoformat(),
            "explicit_chapters_found": len(exp_boundaries),
            "chunks": manifest_chunks
        }
        
        manifest_path = os.path.join(book_out_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
            
        if progress_cb: progress_cb(4, 4, "Fase Chunking Completata!")
        return manifest_path
        
    except Exception as e:
        logger.error(f"Errore in run_semantic_chunker: {e}")
        return None
