import os
import json
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

def run_chapter_grouper(book_name, chunk_dir, progress_cb=None):
    """
    Raggruppa i chunk semantici in macro-capitoli.
    Logica:
    - Raggruppa i chunk in modo sequenziale.
    - Seleziona un chunk_id iniziale.
    - Continua ad aggiungere chunk fino a un massimo (es. 10 chunk per capitolo)
      oppure finché non incontra un chunk che ha un cambio di capitolo esplicito 
      nel testo o nel topic hint, oppure se la dimensione totale in char supera un certo limite.
    """
    try:
        if progress_cb: progress_cb(1, 4, "Lettura dei chunk semantici...")
        manifest_path = os.path.join(chunk_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise Exception("Manifest dei chunk non trovato.")
            
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
            
        chunks_info = manifest.get("chunks", [])
        if not chunks_info:
            if progress_cb: progress_cb(4, 4, "Nessun chunk trovato, termino.")
            return None
            
        chapters = []
        current_chapter_id = 0
        current_chunk_ids = []
        current_char_start = chunks_info[0]["char_start"]
        current_char_end = 0
        
        if progress_cb: progress_cb(2, 4, f"Raggruppamento di {len(chunks_info)} chunk in capitoli logici...")
        # Una logica semplice: raggruppa ogni N chunk per fare un capitolo
        # Se trovassimo veri capitoli potremmo splittare su quelli.
        # Poiché il boss vuole un fallback o una logica semplice:
        for i, c in enumerate(chunks_info):
            current_chunk_ids.append(c["chunk_id"])
            current_char_end = c["char_end"]
            
            # Condizione per chiudere il capitolo:
            # 1. Abbiamo raggiunto 8 chunk
            # 2. Siamo all'ultimo chunk
            if len(current_chunk_ids) >= 8 or i == len(chunks_info) - 1:
                chapters.append({
                    "chapter_id": current_chapter_id,
                    "title": f"Capitolo {current_chapter_id + 1}",
                    "chunk_ids": current_chunk_ids,
                    "char_start": current_char_start,
                    "char_end": current_char_end
                })
                current_chapter_id += 1
                current_chunk_ids = []
                if i < len(chunks_info) - 1:
                    current_char_start = chunks_info[i+1]["char_start"]
                    
        chapter_manifest = {
            "book_name": book_name,
            "total_chapters": len(chapters),
            "created_at": datetime.utcnow().isoformat(),
            "chapters": chapters
        }
        
        if progress_cb: progress_cb(3, 4, f"Salvataggio di {len(chapters)} macro-capitoli...")
        out_dir = os.path.join(os.path.dirname(os.path.dirname(chunk_dir)), "chapters", book_name)
        os.makedirs(out_dir, exist_ok=True)
        
        chapter_manifest_path = os.path.join(out_dir, "chapter_manifest.json")
        with open(chapter_manifest_path, "w", encoding="utf-8") as f:
            json.dump(chapter_manifest, f, ensure_ascii=False, indent=2)
            
        # Copia i file dei chunk nelle cartelle dei capitoli (per la UI/riassunti)
        for cap in chapters:
            cap_dir = os.path.join(out_dir, str(cap["chapter_id"]))
            os.makedirs(cap_dir, exist_ok=True)
            for cid in cap["chunk_ids"]:
                src_chunk = os.path.join(chunk_dir, f"chunk_{cid:03d}.json")
                if os.path.exists(src_chunk):
                    dst_chunk = os.path.join(cap_dir, f"chunk_{cid:03d}.json")
                    import shutil
                    shutil.copyfile(src_chunk, dst_chunk)
                    
        if progress_cb: progress_cb(4, 4, "Raggruppamento capitoli completato con successo!")
        return chapter_manifest_path
        
    except Exception as e:
        logger.error(f"Errore in run_chapter_grouper: {e}")
        return None
