import os
import json
import re
import logging
import boto3
import glob
from datetime import datetime

# Configurazione logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Client AWS per Bedrock (locale)
bedrock = boto3.client("bedrock-runtime", region_name="eu-central-1")

# Costanti
MODEL_ID = 'eu.anthropic.claude-haiku-4-5-20251001-v1:0'
MAX_CHUNKS_PER_LLM_CALL = 80
OVERLAP_SIZE = 10
FALLBACK_CHAPTER_SIZE = 10

def _carica_json_da_locale(file_path: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)

def _salva_json_in_locale(file_path: str, dati: dict):
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(dati, f, ensure_ascii=False, indent=2)

def _carica_tutti_i_chunk(chunk_dir: str, total_chunks: int) -> list:
    chunk_trovati = []
    pattern = os.path.join(chunk_dir, "chunk_*.json")
    for file_path in glob.glob(pattern):
        dati_chunk = _carica_json_da_locale(file_path)
        chunk_trovati.append(dati_chunk)

    chunk_trovati.sort(key=lambda c: c.get('chunk_id', 0))

    if len(chunk_trovati) != total_chunks:
        print(f"⚠️ Attenzione: il manifest dichiara {total_chunks} chunk, ma ne sono stati trovati {len(chunk_trovati)}")

    return chunk_trovati

def _costruisci_riassunti_chunk(chunks: list) -> list:
    righe = []
    for chunk in chunks:
        chunk_id = chunk.get('chunk_id')
        topic = chunk.get('topic_hint', 'N/D')
        testo_inizio = chunk.get('text', '')[:200].replace('\n', ' ').strip()
        entita = chunk.get('entities', [])
        nomi_entita = ", ".join(e.get('word', '') for e in entita[:10])

        riga = f'[{chunk_id}] Topic: "{topic}" | Entità: {nomi_entita} | Inizio: "{testo_inizio}"'
        righe.append(riga)
    return righe

def _costruisci_prompt(riassunti_chunk: list) -> str:
    elenco_chunk = "\n".join(riassunti_chunk)
    prompt = f"""Sei un esperto di letteratura storica italiana. Ti fornisco una lista di sezioni semantiche (chunk) estratte da un libro, ognuna con il suo argomento e le entità principali. Raggruppale in CAPITOLI SEMANTICI.

REGOLE:
- I capitoli devono contenere chunk CONSECUTIVI (non si possono saltare chunk)
- Ogni capitolo raggruppa chunk che trattano uno stesso arco narrativo/tematico
- Un capitolo dovrebbe avere almeno 2-3 chunk e non più di 15-20
- Assegna un titolo descrittivo a ogni capitolo
- Il primo chunk del libro deve essere nel primo capitolo, l'ultimo nell'ultimo

CHUNK:
{elenco_chunk}

FORMATO RISPOSTA (JSON puro, nessun testo aggiuntivo):
{{
  "chapters": [
    {{"chapter_id": 0, "title": "Dedica e premessa", "chunk_ids": [1, 2, 3]}},
    {{"chapter_id": 1, "title": "Novella Prima", "chunk_ids": [4, 5, 6, 7]}}
  ]
}}"""
    return prompt

def _chiama_llm_per_capitoli(riassunti_chunk: list) -> list | None:
    prompt = _costruisci_prompt(riassunti_chunk)
    try:
        corpo_richiesta = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 4000,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}]
        })

        print(f"🏗️ Invocazione Bedrock con modello {MODEL_ID}...")
        risposta = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType='application/json',
            accept='application/json',
            body=corpo_richiesta
        )

        corpo_risposta = json.loads(risposta['body'].read().decode('utf-8'))
        testo_risposta = corpo_risposta['content'][0]['text']
        print(f"🏗️ Risposta LLM ricevuta ({len(testo_risposta)} caratteri)")

        match = re.search(r'\{[\s\S]*\}', testo_risposta)
        if not match:
            print("⚠️ Nessun JSON trovato nella risposta LLM, uso raggruppamento di fallback")
            return None

        dati_risposta = json.loads(match.group())
        capitoli = dati_risposta.get('chapters', [])
        print(f"✅ LLM ha proposto {len(capitoli)} capitoli")
        return capitoli

    except Exception as e:
        print(f"❌ Errore nella chiamata Bedrock / JSON: {str(e)}")
        return None

def _elaborazione_a_finestre(riassunti_chunk: list, chunks: list, progress_cb=None) -> list:
    totale = len(riassunti_chunk)
    tutti_i_capitoli = []
    inizio_finestra = 0
    numero_finestra = 0

    while inizio_finestra < totale:
        fine_finestra = min(inizio_finestra + MAX_CHUNKS_PER_LLM_CALL, totale)
        sottoinsieme = riassunti_chunk[inizio_finestra:fine_finestra]

        print(f"🏗️ Finestra {numero_finestra}: chunk {inizio_finestra} - {fine_finestra - 1} ({len(sottoinsieme)} chunk)")
        if progress_cb: progress_cb(inizio_finestra, totale, f"Finestra {numero_finestra}: analisi LLM di {len(sottoinsieme)} chunk")
        capitoli_finestra = _chiama_llm_per_capitoli(sottoinsieme)

        if capitoli_finestra is None:
            chunk_ids_finestra = [chunks[i].get('chunk_id') for i in range(inizio_finestra, fine_finestra)]
            capitoli_finestra = _crea_capitoli_fallback(chunk_ids_finestra)

        tutti_i_capitoli.append({
            'inizio': inizio_finestra, 'fine': fine_finestra, 'capitoli': capitoli_finestra
        })

        if fine_finestra == totale: break

        inizio_finestra = fine_finestra - OVERLAP_SIZE
        if inizio_finestra >= totale or (totale - inizio_finestra < OVERLAP_SIZE): break

        numero_finestra += 1

    return _unifica_capitoli_da_finestre(tutti_i_capitoli)

def _unifica_capitoli_da_finestre(risultati_finestre: list) -> list:
    if len(risultati_finestre) == 1:
        return risultati_finestre[0]['capitoli']

    capitoli_finali = list(risultati_finestre[0]['capitoli'])
    for idx_finestra in range(1, len(risultati_finestre)):
        capitoli_correnti = risultati_finestre[idx_finestra]['capitoli']
        if not capitoli_correnti: continue

        if capitoli_finali:
            ultimo_capitolo = capitoli_finali[-1]
            ids_ultimo = set(ultimo_capitolo.get('chunk_ids', []))
        else:
            ids_ultimo = set()

        for cap in capitoli_correnti:
            ids_cap = set(cap.get('chunk_ids', []))
            if ids_ultimo and ids_cap & ids_ultimo:
                ids_combinati = list(ultimo_capitolo.get('chunk_ids', []))
                for cid in cap.get('chunk_ids', []):
                    if cid not in ids_combinati: ids_combinati.append(cid)
                ultimo_capitolo['chunk_ids'] = sorted(ids_combinati)
                ids_ultimo = set(ids_combinati)
            else:
                capitoli_finali.append(cap)
                ultimo_capitolo = cap
                ids_ultimo = ids_cap

    for idx, cap in enumerate(capitoli_finali):
        cap['chapter_id'] = idx

    print(f"✅ Unificazione completata: {len(capitoli_finali)} capitoli totali")
    return capitoli_finali

def _valida_capitoli(capitoli_raw: list, tutti_gli_id: list) -> list:
    if not capitoli_raw:
        return _crea_capitoli_fallback(tutti_gli_id)

    try:
        ids_assegnati = []
        for cap in capitoli_raw: ids_assegnati.extend(cap.get('chunk_ids', []))

        insieme_assegnati = set(ids_assegnati)
        insieme_attesi = set(tutti_gli_id)

        if len(ids_assegnati) != len(insieme_assegnati):
            return _crea_capitoli_fallback(tutti_gli_id)

        if insieme_attesi - insieme_assegnati or insieme_assegnati - insieme_attesi:
            return _crea_capitoli_fallback(tutti_gli_id)

        for cap in capitoli_raw:
            ids_cap = sorted(cap.get('chunk_ids', []))
            if len(ids_cap) >= 2:
                for i in range(1, len(ids_cap)):
                    if ids_cap[i] != ids_cap[i - 1] + 1:
                        return _crea_capitoli_fallback(tutti_gli_id)

        return capitoli_raw
    except Exception:
        return _crea_capitoli_fallback(tutti_gli_id)

def _crea_capitoli_fallback(tutti_gli_id: list) -> list:
    ids_ordinati = sorted(tutti_gli_id)
    capitoli = []
    chapter_id = 0
    for i in range(0, len(ids_ordinati), FALLBACK_CHAPTER_SIZE):
        blocco = ids_ordinati[i:i + FALLBACK_CHAPTER_SIZE]
        capitoli.append({"chapter_id": chapter_id, "title": f"Sezione {chapter_id + 1}", "chunk_ids": blocco})
        chapter_id += 1
    return capitoli

def _calcola_metadati_capitoli(capitoli: list, mappa_chunk: dict) -> list:
    capitoli_con_meta = []
    for cap in capitoli:
        ids = sorted(cap.get('chunk_ids', []))
        if not ids: continue

        primo_chunk = mappa_chunk.get(ids[0], {})
        ultimo_chunk = mappa_chunk.get(ids[-1], {})

        capitoli_con_meta.append({
            "chapter_id": cap['chapter_id'],
            "title": cap.get('title', f"Capitolo {cap['chapter_id']}"),
            "chunk_ids": ids,
            "char_start": primo_chunk.get('char_start', 0),
            "char_end": ultimo_chunk.get('char_end', 0)
        })
    return capitoli_con_meta

def _copia_chunk_in_cartelle_capitoli(output_base_dir: str, capitoli: list, mappa_chunk: dict):
    totale_copiati = 0
    for cap in capitoli:
        chapter_id = cap['chapter_id']
        chapter_dir = os.path.join(output_base_dir, str(chapter_id))
        os.makedirs(chapter_dir, exist_ok=True)
        
        for chunk_id in cap['chunk_ids']:
            dati_chunk = mappa_chunk.get(chunk_id)
            if not dati_chunk: continue

            nome_chunk = f"chunk_{chunk_id:03d}.json"
            dest_path = os.path.join(chapter_dir, nome_chunk)
            _salva_json_in_locale(dest_path, dati_chunk)
            totale_copiati += 1
    print(f"✅ {totale_copiati} file chunk copiati nelle cartelle dei capitoli in {output_base_dir}")

def run_chapter_grouper(book_name: str, chunk_dir: str, progress_cb=None) -> str:
    """Entry point locale per raggruppare i chunk semantici in capitoli."""
    try:
        if progress_cb: progress_cb(0, 100, "Caricamento chunk in corso...")
        manifest_path = os.path.join(chunk_dir, "manifest.json")
        manifest = _carica_json_da_locale(manifest_path)
        total_chunks = manifest.get('total_chunks', 0)

        chunks = _carica_tutti_i_chunk(chunk_dir, total_chunks)
        riassunti_chunk = _costruisci_riassunti_chunk(chunks)

        if total_chunks <= MAX_CHUNKS_PER_LLM_CALL:
            if progress_cb: progress_cb(1, 1, "Chiamata LLM per raggruppamento globale...")
            capitoli_raw = _chiama_llm_per_capitoli(riassunti_chunk)
        else:
            capitoli_raw = _elaborazione_a_finestre(riassunti_chunk, chunks, progress_cb)

        tutti_gli_id = [c.get('chunk_id') for c in chunks]
        capitoli_validati = _valida_capitoli(capitoli_raw, tutti_gli_id)

        mappa_chunk = {c.get('chunk_id'): c for c in chunks}
        capitoli_con_meta = _calcola_metadati_capitoli(capitoli_validati, mappa_chunk)

        chapter_manifest = {
            "book_name": book_name,
            "total_chapters": len(capitoli_con_meta),
            "created_at": datetime.utcnow().isoformat(),
            "chapters": capitoli_con_meta
        }
        
        # Salviamo la cartella dei capitoli allo stesso livello di chunk_dir ma si chiama chapter_dir
        # chunk_dir = data/semantic/<book_name>
        # chapters_dir = data/chapters/<book_name>
        base_dir = os.path.dirname(os.path.dirname(chunk_dir)) # "data/"
        chapters_dir = os.path.join(base_dir, "chapters", book_name)
        os.makedirs(chapters_dir, exist_ok=True)
        
        manifest_dest_path = os.path.join(chapters_dir, "chapter_manifest.json")
        _salva_json_in_locale(manifest_dest_path, chapter_manifest)
        print(f"✅ Chapter manifest salvato in {manifest_dest_path}")

        _copia_chunk_in_cartelle_capitoli(chapters_dir, capitoli_con_meta, mappa_chunk)

        if progress_cb: progress_cb(total_chunks, total_chunks, "Raggruppamento capitoli completato!")
        return manifest_dest_path

    except Exception as e:
        print(f"❌ Errore fatale nel chapter grouping: {str(e)}")
        logger.exception("Errore in run_chapter_grouper")
        raise
