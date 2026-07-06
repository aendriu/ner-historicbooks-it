import os
import json
import logging
import re
from datetime import datetime
from typing import Literal
import numpy as np
from sentence_transformers import SentenceTransformer

logger = logging.getLogger(__name__)

# ─── Configurazione chunking ───────────────────────────────────────────────────
MAX_CHUNK_CHARS = 2000
OVERLAP_CHARS = 300
SIMILARITY_THRESHOLD = 0.5        # Soglia cosine similarity embed-method

# Soglie NER-method
NER_SAME_SECTION_THRESHOLD = 2    # entità comuni ≥ 2  → stessa sezione
NER_BOUNDARY_THRESHOLD = 1        # entità comuni < 1  → nuovo capitolo

# Nomi directory per i due metodi
EMBED_SUBDIR = "embed_method"
NER_SUBDIR   = "ner_method"

_model = None


def get_embedding_model():
    global _model
    if _model is None:
        logger.info("Caricamento modello SentenceTransformer: paraphrase-multilingual-MiniLM-L12-v2")
        _model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
    return _model


# ─── Utilità testo ─────────────────────────────────────────────────────────────

def split_into_paragraphs(text):
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
        result.append({"text": p, "char_start": start, "char_end": end})
        current_char = end
    return result


def split_text_with_overlap(text, max_size, overlap):
    words = text.split()
    chunks = []
    current_words = []
    current_len = 0
    i = 0
    while i < len(words):
        w = words[i]
        if current_len + len(w) + 1 > max_size and current_words:
            chunk_str = " ".join(current_words)
            chunks.append(chunk_str)
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
            current_len = sum(len(x) + 1 for x in current_words)
        current_words.append(w)
        current_len += len(w) + 1
        i += 1
    if current_words:
        chunks.append(" ".join(current_words))
    return chunks


# ─── Embed-method helpers ──────────────────────────────────────────────────────

def find_semantic_boundaries(paragraphs):
    if len(paragraphs) < 3:
        return []
    model = get_embedding_model()
    texts = [p["text"] for p in paragraphs]
    embeddings = model.encode(texts)
    boundaries = []
    for i in range(len(embeddings) - 1):
        v1, v2 = embeddings[i], embeddings[i + 1]
        sim = float(np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2)))
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


def build_final_chunks(book_name, text, paragraphs, boundaries, entities):
    boundaries = sorted(list(set(boundaries)))
    if 0 not in boundaries:
        boundaries.insert(0, 0)
    if len(paragraphs) not in boundaries:
        boundaries.append(len(paragraphs))

    final_chunks = []
    chunk_id = 1
    for i in range(len(boundaries) - 1):
        start_idx = boundaries[i]
        end_idx   = boundaries[i + 1]
        section_paras = paragraphs[start_idx:end_idx]
        if not section_paras:
            continue
        section_start = section_paras[0]["char_start"]
        section_end   = section_paras[-1]["char_end"]
        section_text  = text[section_start:section_end]

        if len(section_text) > MAX_CHUNK_CHARS:
            sub_chunks = split_text_with_overlap(section_text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
            curr_start = section_start
            for sc in sub_chunks:
                sc_start = text.find(sc[:50], curr_start)
                if sc_start == -1:
                    sc_start = curr_start
                sc_end = sc_start + len(sc)
                chunk_ents = [e for e in entities if e["start"] >= sc_start and e["end"] <= sc_end]
                final_chunks.append({
                    "book_name": book_name, "chunk_id": chunk_id,
                    "text": sc, "char_start": sc_start, "char_end": sc_end,
                    "topic_hint": f"Sezione Semantica {i + 1} (parte)",
                    "entities": chunk_ents, "num_entities": len(chunk_ents),
                })
                chunk_id += 1
                curr_start = sc_end - OVERLAP_CHARS - 100
                if curr_start < sc_start:
                    curr_start = sc_start
        else:
            chunk_ents = [e for e in entities if e["start"] >= section_start and e["end"] <= section_end]
            final_chunks.append({
                "book_name": book_name, "chunk_id": chunk_id,
                "text": section_text, "char_start": section_start, "char_end": section_end,
                "topic_hint": f"Sezione Semantica {i + 1}",
                "entities": chunk_ents, "num_entities": len(chunk_ents),
            })
            chunk_id += 1

    for c in final_chunks:
        c["total_chunks"] = len(final_chunks)
    return final_chunks


# ─── NER-method ────────────────────────────────────────────────────────────────

def _entity_key(entity: dict) -> str:
    """Chiave normalizzata per confronto entità tra chunk."""
    return f"{entity.get('label', '')}:{entity.get('word', entity.get('text', '')).lower().strip()}"


def _build_chunks_with_ner(book_name: str, text: str, entities: list) -> list:
    """
    Divide il testo in chunk di dimensione massima MAX_CHUNK_CHARS con overlap,
    e assegna le entità a ciascun chunk in base alle coordinate char.
    """
    raw_chunks = split_text_with_overlap(text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
    result = []
    chunk_id = 1
    curr_start = 0
    for raw in raw_chunks:
        sc_start = text.find(raw[:60], curr_start)
        if sc_start == -1:
            sc_start = curr_start
        sc_end = sc_start + len(raw)
        chunk_ents = [e for e in entities if e.get("start", 0) >= sc_start and e.get("end", 0) <= sc_end]
        result.append({
            "book_name": book_name, "chunk_id": chunk_id,
            "text": raw, "char_start": sc_start, "char_end": sc_end,
            "topic_hint": f"Chunk NER {chunk_id}",
            "entities": chunk_ents, "num_entities": len(chunk_ents),
        })
        chunk_id += 1
        curr_start = sc_end - OVERLAP_CHARS - 100
        if curr_start < sc_start:
            curr_start = sc_start
    for c in result:
        c["total_chunks"] = len(result)
    return result


def run_ner_chunker(book_name: str, clean_file_path: str, ner_file_path: str,
                   output_dir: str, progress_cb=None) -> str | None:
    """
    Metodo NER-based: raggruppa i chunk in sezioni semantiche confrontando
    la sovrapposizione di entità tra chunk adiacenti.

    Algoritmo:
    - Per ogni coppia X, X+1:
        - Se entità comuni >= NER_SAME_SECTION_THRESHOLD  → stessa sezione
        - Se entità comuni <  NER_BOUNDARY_THRESHOLD      → nuovo capitolo
    """
    try:
        if progress_cb: progress_cb(0, 4, "Caricamento testo ed entità NER...")
        with open(clean_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        text = data.get("contenuto", data.get("text", data.get("content", "")))

        with open(ner_file_path, "r", encoding="utf-8") as f:
            ner_data = json.load(f)
        entities = ner_data.get("entities", [])

        if progress_cb: progress_cb(1, 4, "Creazione chunk con entità NER assegnate...")
        chunks = _build_chunks_with_ner(book_name, text, entities)

        if progress_cb: progress_cb(2, 4, f"Calcolo boundaries NER su {len(chunks)} chunk...")

        # Calcola boundaries tramite sovrapposizione entità
        boundaries: list[int] = [0]
        for i in range(len(chunks) - 1):
            keys_x  = set(_entity_key(e) for e in chunks[i]["entities"])
            keys_x1 = set(_entity_key(e) for e in chunks[i + 1]["entities"])
            common  = len(keys_x & keys_x1)
            if common < NER_BOUNDARY_THRESHOLD:
                boundaries.append(i + 1)

        # Raggruppa chunk in sezioni semantiche
        boundaries.append(len(chunks))
        final_chunks = []
        chunk_id = 1
        for b_idx in range(len(boundaries) - 1):
            seg_start = boundaries[b_idx]
            seg_end   = boundaries[b_idx + 1]
            seg_chunks = chunks[seg_start:seg_end]
            if not seg_chunks:
                continue

            section_text  = " ".join(c["text"] for c in seg_chunks)
            section_start = seg_chunks[0]["char_start"]
            section_end   = seg_chunks[-1]["char_end"]
            all_ents      = []
            seen_keys     = set()
            for sc in seg_chunks:
                for e in sc["entities"]:
                    k = _entity_key(e)
                    if k not in seen_keys:
                        all_ents.append(e)
                        seen_keys.add(k)

            # Se la sezione è troppo grande, spezzala rispettando MAX_CHUNK_CHARS
            if len(section_text) > MAX_CHUNK_CHARS:
                sub_texts = split_text_with_overlap(section_text, MAX_CHUNK_CHARS, OVERLAP_CHARS)
                curr_start = section_start
                for sub in sub_texts:
                    sc_start = text.find(sub[:50], curr_start)
                    if sc_start == -1:
                        sc_start = curr_start
                    sc_end = sc_start + len(sub)
                    sub_ents = [e for e in all_ents if e.get("start", 0) >= sc_start and e.get("end", 0) <= sc_end]
                    final_chunks.append({
                        "book_name": book_name, "chunk_id": chunk_id,
                        "text": sub, "char_start": sc_start, "char_end": sc_end,
                        "topic_hint": f"Sezione NER {b_idx + 1} (parte)",
                        "entities": sub_ents, "num_entities": len(sub_ents),
                    })
                    chunk_id += 1
                    curr_start = sc_end - OVERLAP_CHARS - 100
                    if curr_start < sc_start:
                        curr_start = sc_start
            else:
                final_chunks.append({
                    "book_name": book_name, "chunk_id": chunk_id,
                    "text": section_text, "char_start": section_start, "char_end": section_end,
                    "topic_hint": f"Sezione NER {b_idx + 1}",
                    "entities": all_ents, "num_entities": len(all_ents),
                })
                chunk_id += 1

        for c in final_chunks:
            c["total_chunks"] = len(final_chunks)

        if progress_cb: progress_cb(3, 4, "Salvataggio risultati NER method...")
        book_out_dir = os.path.join(output_dir, NER_SUBDIR, book_name)
        os.makedirs(book_out_dir, exist_ok=True)

        manifest_chunks = []
        for c in final_chunks:
            c_file = os.path.join(book_out_dir, f"chunk_{c['chunk_id']:03d}.json")
            with open(c_file, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
            manifest_chunks.append({
                "chunk_id": c["chunk_id"],
                "topic_hint": c["topic_hint"],
                "char_start": c["char_start"],
                "char_end": c["char_end"],
                "num_entities": c["num_entities"],
                "text_length": len(c["text"]),
            })

        manifest = {
            "book_name": book_name,
            "method": "ner",
            "total_chunks": len(final_chunks),
            "created_at": datetime.utcnow().isoformat(),
            "ner_same_section_threshold": NER_SAME_SECTION_THRESHOLD,
            "ner_boundary_threshold": NER_BOUNDARY_THRESHOLD,
            "chunks": manifest_chunks,
        }
        manifest_path = os.path.join(book_out_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        if progress_cb: progress_cb(4, 4, f"Chunking NER completato: {len(final_chunks)} chunk.")
        return manifest_path

    except Exception as e:
        logger.error(f"Errore in run_ner_chunker: {e}")
        return None


# ─── Entry point unificato ─────────────────────────────────────────────────────

def run_semantic_chunker(book_name: str, clean_file_path: str, ner_file_path: str,
                         output_dir: str, progress_cb=None,
                         method: Literal["embed", "ner"] = "embed") -> str | None:
    """
    Esegue il chunking semantico con il metodo scelto.
    - method="embed"  → similarità coseno degli embedding (default)
    - method="ner"    → sovrapposizione entità NER tra chunk adiacenti
    """
    if method == "ner":
        return run_ner_chunker(book_name, clean_file_path, ner_file_path, output_dir, progress_cb)

    # ── Embed method ──────────────────────────────────────────────────────────
    try:
        if progress_cb: progress_cb(0, 4, "Caricamento testi...")
        with open(clean_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        text = data.get("contenuto", data.get("text", data.get("content", "")))

        with open(ner_file_path, "r", encoding="utf-8") as f:
            ner_data = json.load(f)
        entities = ner_data.get("entities", [])

        if progress_cb: progress_cb(1, 4, "Calcolo embedding e boundaries...")
        paragraphs    = split_into_paragraphs(text)
        sem_bounds    = find_semantic_boundaries(paragraphs)
        exp_bounds    = find_explicit_chapters(paragraphs)
        all_boundaries = sem_bounds + exp_bounds

        if progress_cb: progress_cb(2, 4, f"Creazione chunk (max {MAX_CHUNK_CHARS}, overlap {OVERLAP_CHARS})...")
        chunks = build_final_chunks(book_name, text, paragraphs, all_boundaries, entities)

        if progress_cb: progress_cb(3, 4, "Salvataggio risultati embed method...")
        book_out_dir = os.path.join(output_dir, EMBED_SUBDIR, book_name)
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
                "text_length": len(c["text"]),
            })

        manifest = {
            "book_name": book_name,
            "method": "embed",
            "total_chunks": len(chunks),
            "created_at": datetime.utcnow().isoformat(),
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "explicit_chapters_found": len(exp_bounds),
            "chunks": manifest_chunks,
        }
        manifest_path = os.path.join(book_out_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        if progress_cb: progress_cb(4, 4, "Chunking Embed completato!")
        return manifest_path

    except Exception as e:
        logger.error(f"Errore in run_semantic_chunker (embed): {e}")
        return None
