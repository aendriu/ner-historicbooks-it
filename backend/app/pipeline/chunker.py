import os
import json
import logging
import re
from datetime import datetime
from typing import Literal
import numpy as np
import requests
from app.config import settings

logger = logging.getLogger(__name__)

# ─── Configurazione chunking ───────────────────────────────────────────────────
MAX_CHUNK_CHARS = 2000
OVERLAP_CHARS = 300
SIMILARITY_THRESHOLD = 0.35       # Soglia cosine similarity embed-method 

# Soglie NER-method
NER_SAME_SECTION_THRESHOLD = 2    # entità comuni ≥ 2  → stessa sezione
NER_BOUNDARY_THRESHOLD = 1        # entità comuni < 1  → nuovo capitolo (taglia solo se 0 entità condivise)

# Nomi directory per i due metodi
EMBED_SUBDIR = "embed_method"
NER_SUBDIR   = "ner_method"

def _get_ollama_embeddings(texts: list[str]) -> np.ndarray:
    """Chiama l'API /api/embed di Ollama per ottenere gli embedding dei testi.

    Usa lo stesso host/port configurato per i riassunti.
    Il modello viene letto a runtime da settings.EMBED_MODEL.

    Args:
        texts: lista di testi da vettorializzare.

    Returns:
        Array numpy con gli embedding.

    Raises:
        RuntimeError: se la chiamata all'API fallisce.
    """
    host = settings.OLLAMA_HOST.rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = f"http://{host}:{settings.OLLAMA_PORT}"
    url = f"{host}/api/embed"
    model = settings.EMBED_MODEL   # letto a runtime → aggiornabile senza restart
    try:
        r = requests.post(url, json={"model": model, "input": texts}, timeout=120)
        r.raise_for_status()
        embeddings = r.json()["embeddings"]
        return np.array(embeddings, dtype=np.float32)
    except Exception as e:
        raise RuntimeError(f"Ollama embedding fallito: {e}") from e




# ─── Utilità testo ─────────────────────────────────────────────────────────────

# Dimensione target per gli pseudo-paragrafi (in caratteri)
TARGET_SIZE = 500


def split_into_paragraphs(text):
    """Divide il testo in pseudo-paragrafi di circa TARGET_SIZE caratteri.

    Cerca di non spezzare le frasi usando la punteggiatura finale (.!?).
    Gestisce in modo sicuro i libri sprovvisti di ritorni a capo.
    """
    result = []
    
    # Suddividiamo il testo in frasi usando la punteggiatura
    # Riconosce il punto, punto interrogativo, esclamativo seguito da spazio o a capo.
    sentences = re.split(r'(?<=[.!?])[\s\n]+', text)
    
    current_para_text = ""
    current_start = 0
    
    for s in sentences:
        s = s.strip()
        if not s:
            continue
            
        if current_para_text:
            current_para_text += " " + s
        else:
            current_para_text = s
            
        if len(current_para_text) >= TARGET_SIZE:
            start_idx = text.find(current_para_text[:50], current_start)
            if start_idx == -1:
                start_idx = current_start
                
            end_idx = start_idx + len(current_para_text)
            
            result.append({
                "text": current_para_text,
                "char_start": start_idx,
                "char_end": end_idx
            })
            
            current_start = end_idx
            current_para_text = ""
            
    # Aggiungiamo l'ultimo pezzetto rimasto
    if current_para_text:
        start_idx = text.find(current_para_text[:50], current_start)
        if start_idx == -1:
            start_idx = current_start
        end_idx = start_idx + len(current_para_text)
        result.append({
            "text": current_para_text,
            "char_start": start_idx,
            "char_end": end_idx
        })
        
    return result


def split_text_semantic(text: str, max_size: int, overlap: int, entities: list = None) -> list[tuple[str, int, int]]:
    """Divide il testo in chunk semanticamente coerenti usando un approccio a cascata.

    Strategie di divisione (in ordine di priorità):
    1. Cambio significativo nella finestra di entità NER (se disponibili).
    2. Doppio ritorno a capo (paragrafo) più vicino al limite.
    3. Punteggiatura finale (. ! ?) più vicina al limite.
    4. Ultima spiaggia: taglia allo spazio più vicino.

    Returns:
        Lista di tuple (testo, char_start_assoluto, char_end_assoluto).
    """
    if not text:
        return []

    MIN_CHUNK = max_size // 3      # Dimensione minima per non creare chunk-stuzzichino
    NER_WINDOW = 300               # Ampiezza finestra NER per confronto (caratteri)
    NER_CHANGE_THRESHOLD = 0.4     # Jaccard < 0.4 = cambio di contesto significativo

    results: list[tuple[str, int, int]] = []
    start = 0

    while start < len(text):
        remaining = len(text) - start
        if remaining <= max_size:
            chunk = text[start:].strip()
            if chunk:
                results.append((chunk, start, start + len(chunk)))
            break

        end_candidate = start + max_size
        cut_point = None

        # ── STRATEGIA 1: cambio di entità NER nella zona finale del chunk ──
        if entities and cut_point is None:
            zone_start = start + MIN_CHUNK
            zone_mid   = end_candidate - NER_WINDOW // 2
            zone_end   = end_candidate

            if zone_mid > zone_start:
                ents_before = set(
                    _entity_key(e) for e in entities
                    if zone_start <= e.get("start", e.get("char_start", 0)) < zone_mid
                )
                ents_after = set(
                    _entity_key(e) for e in entities
                    if zone_mid <= e.get("start", e.get("char_start", 0)) < zone_end
                )
                if ents_before and ents_after:
                    union = len(ents_before | ents_after)
                    jaccard = len(ents_before & ents_after) / union if union > 0 else 1.0
                    if jaccard < NER_CHANGE_THRESHOLD:
                        # Cambio rilevato: cerca \ n\ n vicino al punto di cambio
                        nn = text.rfind('\n\n', zone_start, zone_mid + NER_WINDOW)
                        if nn != -1:
                            cut_point = nn + 2
                        else:
                            # Cerca punteggiatura vicino al punto di cambio
                            for k in range(zone_mid, zone_start, -1):
                                if text[k] in '.!?':
                                    cut_point = k + 1
                                    break

        # ── STRATEGIA 2: paragrafo (doppio ritorno a capo) ──
        if cut_point is None:
            nn = text.rfind('\n\n', start + MIN_CHUNK, end_candidate)
            if nn != -1:
                cut_point = nn + 2

        # ── STRATEGIA 3: punteggiatura finale ──
        if cut_point is None:
            for k in range(end_candidate, start + MIN_CHUNK, -1):
                if k < len(text) and text[k] in '.!?':
                    cut_point = k + 1
                    break

        # ── STRATEGIA 4 (fallback duro): spazio più vicino ──
        if cut_point is None:
            sp = text.rfind(' ', start + MIN_CHUNK, end_candidate)
            cut_point = sp + 1 if sp != -1 else end_candidate

        chunk = text[start:cut_point].strip()
        if chunk:
            results.append((chunk, start, start + len(text[start:cut_point])))

        # Overlap: torna indietro di `overlap` caratteri fermandoti a una frase
        overlap_start = max(start, cut_point - overlap)
        for k in range(overlap_start, cut_point):
            if k < len(text) and text[k] in '.!?\n':
                overlap_start = k + 1
                break

        start = overlap_start if overlap_start < cut_point else cut_point

    return results


def split_text_with_overlap(text, max_size, overlap):
    """Wrapper di retrocompatibilità – restituisce solo le stringhe."""
    return [t for t, _, _ in split_text_semantic(text, max_size, overlap)]


# ─── Embed-method helpers ──────────────────────────────────────────────────────

def find_semantic_boundaries(paragraphs):
    if len(paragraphs) < 3:
        return []
    texts = [p["text"] for p in paragraphs]
    logger.info(f"Calcolo embedding per {len(texts)} paragrafi con {SEMANTIC_EMBEDDING_MODEL} via Ollama...")
    embeddings = _get_ollama_embeddings(texts)
    boundaries = []
    for i in range(len(embeddings) - 1):
        v1, v2 = embeddings[i], embeddings[i + 1]
        norm1, norm2 = np.linalg.norm(v1), np.linalg.norm(v2)
        if norm1 == 0 or norm2 == 0:
            continue
        sim = float(np.dot(v1, v2) / (norm1 * norm2))
        if sim < SIMILARITY_THRESHOLD:
            boundaries.append(i + 1)
    return boundaries


def find_explicit_chapters(paragraphs):
    boundaries = []
    pattern = re.compile(r'\b(CAPITOLO|CAPO|CAP\.|LIBRO|PARTE)\s+([IVXLCDM]+|\d+)\b', re.IGNORECASE)
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

        # ── Sentence boundary alignment ──
        # Se il taglio di capitolo cade a metà frase (es. per un \n\n nel mezzo
        # di una frase OCR), avanziamo fino al prossimo punto fermo nel testo.
        raw_end_char = text[section_end - 1] if section_end > 0 else ''
        if raw_end_char not in '.!?"\'»\n' and i < len(boundaries) - 2:
            search_limit = min(section_end + 300, len(text))
            for k in range(section_end, search_limit):
                if text[k] in '.!?':
                    section_end = k + 1
                    break

        section_text  = text[section_start:section_end]

        if len(section_text) > MAX_CHUNK_CHARS:
            # Entità relative alla sezione corrente con posizioni assolute
            section_ents = [e for e in entities if e.get("start", 0) >= section_start and e.get("end", 0) <= section_end]
            sub_chunks = split_text_semantic(section_text, MAX_CHUNK_CHARS, OVERLAP_CHARS, entities=section_ents)
            for sc_text, sc_rel_start, sc_rel_end in sub_chunks:
                sc_start = section_start + sc_rel_start
                sc_end   = section_start + sc_rel_end
                chunk_ents = [e for e in entities if e.get("start", 0) >= sc_start and e.get("end", 0) <= sc_end]
                final_chunks.append({
                    "book_name": book_name, "chunk_id": chunk_id,
                    "text": sc_text, "char_start": sc_start, "char_end": sc_end,
                    "topic_hint": f"Capitolo Semantico {i + 1} (parte)",
                    "entities": chunk_ents, "num_entities": len(chunk_ents),
                })
                chunk_id += 1
        else:
            chunk_ents = [e for e in entities if e["start"] >= section_start and e["end"] <= section_end]
            final_chunks.append({
                "book_name": book_name, "chunk_id": chunk_id,
                "text": section_text, "char_start": section_start, "char_end": section_end,
                "topic_hint": f"Capitolo Semantico {i + 1}",
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
    raw_chunks = split_text_semantic(text, MAX_CHUNK_CHARS, OVERLAP_CHARS, entities=entities)
    result = []
    chunk_id = 1
    for sc_text, sc_start, sc_end in raw_chunks:
        chunk_ents = [e for e in entities if e.get("start", 0) >= sc_start and e.get("end", 0) <= sc_end]
        result.append({
            "book_name": book_name, "chunk_id": chunk_id,
            "text": sc_text, "char_start": sc_start, "char_end": sc_end,
            "topic_hint": f"Chunk NER {chunk_id}",
            "entities": chunk_ents, "num_entities": len(chunk_ents),
        })
        chunk_id += 1
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

        # Calcola boundaries tramite sovrapposizione entità (finestra scorrevole)
        # Confronta le entità del gruppo corrente (ultimi NER_WINDOW chunk) con il chunk successivo.
        # Questo evita l'over-segmentazione: un'entità citata 2 chunk fa vale ancora come "in scope".
        NER_WINDOW = 4   # numero di chunk da includere nella finestra di contesto corrente
        boundaries: list[int] = [0]
        for i in range(len(chunks) - 1):
            win_start = max(0, i - NER_WINDOW + 1)
            keys_window = set()
            for w in range(win_start, i + 1):
                for e in chunks[w]["entities"]:
                    keys_window.add(_entity_key(e))
            keys_next = set(_entity_key(e) for e in chunks[i + 1]["entities"])
            common = len(keys_window & keys_next)
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

        # ── Livello 2: aggrega le sezioni NER in capitoli ──────────────────────
        # Le sezioni L1 sono granulari (tagliano ad ogni 0-entity gap).
        # Qui le raggruppiamo in capitoli usando la stessa logica ma con
        # finestra e soglia più permissive (opero su sezioni, non su chunk).
        NER_L2_WINDOW    = 3   # guarda le ultime 3 sezioni
        NER_L2_THRESHOLD = 2   # taglia solo se entità comuni < 2

        import re as _re

        # Raccogli entity keys per sezione (raggruppa chunk con stesso topic_hint)
        section_entity_keys: dict[int, set] = {}
        for c in final_chunks:
            m = _re.search(r'(\d+)', c.get("topic_hint", ""))
            sid = int(m.group(1)) if m else 0
            if sid not in section_entity_keys:
                section_entity_keys[sid] = set()
            for e in c.get("entities", []):
                section_entity_keys[sid].add(_entity_key(e))

        sec_ids = sorted(section_entity_keys.keys())

        # Calcola boundaries L2
        l2_bounds = [0]
        for i in range(len(sec_ids) - 1):
            win_start = max(0, i - NER_L2_WINDOW + 1)
            keys_win = set()
            for w in range(win_start, i + 1):
                keys_win |= section_entity_keys[sec_ids[w]]
            keys_next = section_entity_keys[sec_ids[i + 1]]
            if len(keys_win & keys_next) < NER_L2_THRESHOLD:
                l2_bounds.append(i + 1)
        l2_bounds.append(len(sec_ids))

        # Mappa sezione → capitolo e costruisci metadata capitoli
        sec_to_ch: dict[int, int] = {}
        chapters_meta = []
        for ch_idx in range(len(l2_bounds) - 1):
            ch_num     = ch_idx + 1
            sl         = slice(l2_bounds[ch_idx], l2_bounds[ch_idx + 1])
            ch_sec_ids = sec_ids[sl]
            for sid in ch_sec_ids:
                sec_to_ch[sid] = ch_num
            ch_chunks = [c for c in final_chunks
                         if int((_re.search(r'(\d+)', c.get("topic_hint","0")) or type('',(),{'group':lambda s,i:"0"})()).group(1))
                         in ch_sec_ids]
            chapters_meta.append({
                "chapter_id":   ch_num,
                "chapter_hint": f"Capitolo NER {ch_num}",
                "section_ids":  list(ch_sec_ids),
                "num_sections": len(ch_sec_ids),
                "char_start":   min((c["char_start"] for c in ch_chunks), default=0),
                "char_end":     max((c["char_end"]   for c in ch_chunks), default=0),
            })

        # Aggiungi chapter_id e chapter_hint a ogni chunk
        for c in final_chunks:
            m = _re.search(r'(\d+)', c.get("topic_hint", "0"))
            sid = int(m.group(1)) if m else 0
            ch_num = sec_to_ch.get(sid, 1)
            c["chapter_id"]   = ch_num
            c["chapter_hint"] = f"Capitolo NER {ch_num}"

        logger.info(f"NER L2: {len(sec_ids)} sezioni → {len(chapters_meta)} capitoli")

        if progress_cb: progress_cb(3, 4, f"Salvataggio NER ({len(chapters_meta)} capitoli L2)...")
        book_out_dir = os.path.join(output_dir, NER_SUBDIR, book_name)
        os.makedirs(book_out_dir, exist_ok=True)

        manifest_chunks = []
        for c in final_chunks:
            c_file = os.path.join(book_out_dir, f"chunk_{c['chunk_id']:03d}.json")
            with open(c_file, "w", encoding="utf-8") as f:
                json.dump(c, f, ensure_ascii=False, indent=2)
            manifest_chunks.append({
                "chunk_id":    c["chunk_id"],
                "topic_hint":  c["topic_hint"],
                "chapter_id":  c["chapter_id"],
                "chapter_hint":c["chapter_hint"],
                "char_start":  c["char_start"],
                "char_end":    c["char_end"],
                "num_entities":c["num_entities"],
                "text_length": len(c["text"]),
            })

        manifest = {
            "book_name":       book_name,
            "method":          "ner",
            "total_chunks":    len(final_chunks),
            "total_chapters":  len(chapters_meta),
            "created_at":      datetime.utcnow().isoformat(),
            "ner_boundary_threshold": NER_BOUNDARY_THRESHOLD,
            "ner_l2_window":          NER_L2_WINDOW,
            "ner_l2_threshold":       NER_L2_THRESHOLD,
            "chapters": chapters_meta,
            "chunks":   manifest_chunks,
        }
        manifest_path = os.path.join(book_out_dir, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)

        if progress_cb: progress_cb(4, 4, f"NER completato: {len(final_chunks)} sezioni → {len(chapters_meta)} capitoli.")
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
