import os
import json
import re
import boto3
from datetime import datetime

# ──────────────────────────────────────────────────────────────
# Costanti di configurazione
# ──────────────────────────────────────────────────────────────
MODEL_ID = "eu.anthropic.claude-haiku-4-5-20251001-v1:0"
WINDOW_SIZE = 18          # paragrafi per finestra
OVERLAP = 3               # paragrafi di sovrapposizione tra finestre
MIN_CHUNK_CHARS = 2000    # dimensione minima di un chunk (caratteri)
MAX_CHUNK_CHARS = 8000    # dimensione massima di un chunk (caratteri)
OVERLAP_CHARS = 300       # overlap matematico tra i chunk (caratteri)

# Inizializziamo solo Bedrock (siamo in locale, non serve S3)
bedrock = boto3.client("bedrock-runtime", region_name="eu-central-1")

# ──────────────────────────────────────────────────────────────
# Regex per marcatori espliciti di capitolo
# ──────────────────────────────────────────────────────────────
CHAPTER_PATTERNS = [
    re.compile(r"^\s*(CAPITOLO|CAPO|CAP\.?)\s+([IVXLCDM]+|\d+)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*(LIBRO|PARTE)\s+([IVXLCDM]+|\d+)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*NOVELLA\s+([IVXLCDM]+|\d+)", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*([IVXLCDM]{1,15})\s*$", re.MULTILINE),
    re.compile(r"^\s*\d+\.\s+[A-Z]", re.MULTILINE),
]

def _carica_testo(clean_file_path: str) -> str:
    print(f"📖 Caricamento testo pulito da {clean_file_path}")
    with open(clean_file_path, "r", encoding="utf-8") as f:
        dati = json.load(f)
    for campo in ("contenuto", "text", "content"):
        if campo in dati:
            return dati[campo]
    raise KeyError("Nessun campo di testo trovato nel file pulito.")

def _carica_entita(ner_file_path: str) -> list:
    print(f"🏷️  Caricamento entità NER da {ner_file_path}")
    with open(ner_file_path, "r", encoding="utf-8") as f:
        dati = json.load(f)
    return dati.get("entities", [])

# (Manteniamo intatte le funzioni di split dei paragrafi)
def _suddividi_paragrafi(testo: str) -> list[dict]:
    paragrafi = _split_e_traccia(testo, r'\n\s*\n')
    if len(paragrafi) >= 3:
        return paragrafi
    paragrafi = _split_e_traccia(testo, r'\n')
    if len(paragrafi) >= 3:
        return paragrafi
    return _split_per_frasi(testo, target_size=2000)

def _split_e_traccia(testo: str, pattern: str) -> list[dict]:
    blocchi_raw = re.split(pattern, testo)
    paragrafi = []
    posizione_ricerca = 0
    for blocco in blocchi_raw:
        strippato = blocco.strip()
        if len(strippato) < 3:
            continue
        frammento = strippato[:50]
        indice = testo.find(frammento, posizione_ricerca)
        if indice == -1:
            indice = posizione_ricerca
        char_start = indice
        char_end = char_start + len(strippato)
        paragrafi.append({"text": strippato, "char_start": char_start, "char_end": char_end})
        posizione_ricerca = char_end
    return paragrafi

def _split_per_frasi(testo: str, target_size: int = 2000) -> list[dict]:
    confini = [m.end() for m in re.finditer(r'[.!?]+\s+(?=[A-ZÀÈÉÌÒÙ])', testo)]
    if len(confini) < 10:
        confini = [m.end() for m in re.finditer(r'[.!?]+\s+', testo)]
    if len(confini) < 5:
        confini = [m.start() for m in re.finditer(r'\s+', testo) if m.start() > 0]
    paragrafi = []
    inizio = 0
    for confine in confini:
        if confine - inizio >= target_size:
            blocco = testo[inizio:confine].strip()
            if len(blocco) >= 3:
                paragrafi.append({"text": blocco, "char_start": inizio, "char_end": confine})
            inizio = confine
    if inizio < len(testo):
        blocco = testo[inizio:].strip()
        if len(blocco) >= 3:
            paragrafi.append({"text": blocco, "char_start": inizio, "char_end": len(testo)})
    if len(paragrafi) < 3:
        paragrafi = []
        for i in range(0, len(testo), target_size):
            fine = min(i + target_size, len(testo))
            if fine < len(testo):
                spazio = testo.rfind(' ', i, fine)
                if spazio > i:
                    fine = spazio + 1
            blocco = testo[i:fine].strip()
            if len(blocco) >= 3:
                paragrafi.append({"text": blocco, "char_start": i, "char_end": fine})
    return paragrafi

def _trova_marcatori_capitolo(paragrafi: list[dict]) -> list[int]:
    confini = []
    for idx, par in enumerate(paragrafi):
        for pattern in CHAPTER_PATTERNS:
            if pattern.search(par["text"]):
                confini.append(idx)
                break
    return confini

PROMPT_TEMPLATE = """\
Sei un esperto di testi storici italiani. Analizza il seguente estratto di un libro e identifica dove cadono i confini semantici, ovvero i punti in cui il testo cambia argomento, scena, o evento principale.

ENTITÀ RILEVANTI IN QUESTA SEZIONE:
{entities_list}

TESTO (diviso in paragrafi numerati):
{numbered_paragraphs}

ISTRUZIONI:
- Restituisci SOLO un JSON con i numeri dei paragrafi DOPO i quali va inserito un taglio semantico.
- Un taglio va dove il testo passa a un argomento/evento/scena diverso.
- NON tagliare all'interno di una scena o un ragionamento continuo.
- Assegna un breve "topic_hint" (max 10 parole) per ogni sezione risultante.
- Se non ci sono confini chiari, restituisci un array vuoto per "boundaries".

FORMATO RISPOSTA (JSON puro, nessun testo aggiuntivo):
{{
  "boundaries": [3, 7, 12],
  "topics": ["Dedica iniziale", "Arrivo dei mercanti", "Il banchetto"]
}}"""

def _entita_nella_finestra(entita: list, char_inizio: int, char_fine: int) -> list[dict]:
    mappa = {}
    for ent in entita:
        ent_start = ent.get("start", -1)
        ent_end = ent.get("end", -1)
        if ent_start >= char_inizio and ent_end <= char_fine:
            parola = ent.get("word", ent.get("text", ""))
            punteggio = ent.get("score", 0)
            if parola not in mappa or punteggio > mappa[parola]["score"]:
                mappa[parola] = {"word": parola, "label": ent["label"], "score": punteggio}
    ordinate = sorted(mappa.values(), key=lambda x: x["score"], reverse=True)
    return ordinate[:20]

def _chiama_bedrock(prompt: str) -> str | None:
    try:
        corpo = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 2000,
            "temperature": 0.2,
            "messages": [{"role": "user", "content": prompt}],
        })
        risposta = bedrock.invoke_model(
            modelId=MODEL_ID,
            contentType="application/json",
            accept="application/json",
            body=corpo,
        )
        risultato = json.loads(risposta["body"].read())
        return risultato["content"][0]["text"]
    except Exception as e:
        print(f"⚠️  Errore nella chiamata a Bedrock: {e}")
        return None

def _parsa_risposta_llm(testo_risposta: str) -> tuple[list[int], list[str]]:
    match = re.search(r"\{[\s\S]*\}", testo_risposta)
    if not match:
        return [], []
    try:
        dati = json.loads(match.group())
        boundaries = [int(b) for b in dati.get("boundaries", [])]
        return boundaries, dati.get("topics", [])
    except Exception:
        return [], []

def _rileva_confini_llm(paragrafi: list[dict], entita: list, progress_cb=None) -> tuple[list[int], dict[int, str]]:
    tutti_confini = []
    mappa_topic: dict[int, str] = {}
    num_paragrafi = len(paragrafi)
    inizio_finestra = 0
    while inizio_finestra < num_paragrafi:
        fine_finestra = min(inizio_finestra + WINDOW_SIZE, num_paragrafi)
        finestra = paragrafi[inizio_finestra:fine_finestra]
        char_inizio = finestra[0]["char_start"]
        char_fine = finestra[-1]["char_end"]
        ent_finestra = _entita_nella_finestra(entita, char_inizio, char_fine)
        lista_ent = ", ".join(f"{e['word']} ({e['label']})" for e in ent_finestra) if ent_finestra else "(nessuna entità)"
        
        righe = []
        for i, par in enumerate(finestra):
            numero_globale = inizio_finestra + i + 1
            righe.append(f"[{numero_globale}] {par['text'][:500]}")
        testo_numerato = "\n\n".join(righe)

        prompt = PROMPT_TEMPLATE.format(entities_list=lista_ent, numbered_paragraphs=testo_numerato)
        print(f"✂️  Finestra paragrafi {inizio_finestra + 1}-{fine_finestra} inviata a Bedrock")
        if progress_cb: progress_cb(inizio_finestra + 1, num_paragrafi, f"Analisi semantica LLM: finestre {inizio_finestra + 1}-{fine_finestra} di {num_paragrafi}")
        
        risposta = _chiama_bedrock(prompt)
        if risposta:
            boundaries, topics = _parsa_risposta_llm(risposta)
            for b in boundaries:
                if inizio_finestra < b < fine_finestra:
                    tutti_confini.append(b)
            punti = [inizio_finestra] + [b for b in boundaries if inizio_finestra < b < fine_finestra] + [fine_finestra]
            for t_idx, topic in enumerate(topics):
                if t_idx < len(punti) - 1:
                    mappa_topic[punti[t_idx]] = topic

        if fine_finestra >= num_paragrafi:
            break
        inizio_finestra = fine_finestra - OVERLAP
    return tutti_confini, mappa_topic

def _unisci_e_filtra_confini(confini_espliciti: list[int], confini_llm: list[int], paragrafi: list[dict]) -> list[int]:
    tutti = sorted(set(confini_espliciti + confini_llm))
    if not tutti: return []
    
    uniti = [tutti[0]]
    for c in tutti[1:]:
        if c - uniti[-1] > 1:
            uniti.append(c)
            
    punti = [0] + uniti + [len(paragrafi)]
    nuovi_punti = [0]
    
    for i in range(1, len(punti)):
        inizio = nuovi_punti[-1]
        fine = punti[i]
        
        char_start = paragrafi[inizio]["char_start"]
        char_end = paragrafi[fine - 1]["char_end"]
        lunghezza = char_end - char_start
        
        if i == len(punti) - 1:
            if lunghezza < MIN_CHUNK_CHARS and len(nuovi_punti) > 1:
                pass
            else:
                nuovi_punti.append(fine)
        else:
            if lunghezza >= MIN_CHUNK_CHARS:
                nuovi_punti.append(fine)
                
    if nuovi_punti[-1] != len(paragrafi):
        nuovi_punti.append(len(paragrafi))
        
    if len(nuovi_punti) > 2:
        char_start = paragrafi[nuovi_punti[-2]]["char_start"]
        char_end = paragrafi[nuovi_punti[-1]-1]["char_end"]
        if (char_end - char_start) < MIN_CHUNK_CHARS:
            nuovi_punti.pop(-2)
            
    return nuovi_punti[1:-1]

def _crea_chunk(paragrafi: list[dict], confini: list[int], mappa_topic: dict[int, str], entita: list, nome_libro: str, testo: str) -> list[dict]:
    punti_taglio = sorted(set([0] + confini + [len(paragrafi)]))
    chunks = []
    for i in range(len(punti_taglio) - 1):
        inizio = punti_taglio[i]
        fine = punti_taglio[i + 1]
        segmento = paragrafi[inizio:fine]
        if not segmento: continue
        
        char_start = segmento[0]["char_start"]
        char_end = segmento[-1]["char_end"]

        if i > 0:
            target_start = max(0, char_start - OVERLAP_CHARS)
            while target_start < char_start and target_start > 0 and testo[target_start - 1] not in (' ', '\n'):
                target_start += 1
            char_start = target_start

        testo_chunk = testo[char_start:char_end].strip()

        topic = mappa_topic.get(inizio, "")
        if not topic:
            for delta in range(3):
                if (inizio + delta) in mappa_topic:
                    topic = mappa_topic[inizio + delta]
                    break
                if (inizio - delta) in mappa_topic and delta > 0:
                    topic = mappa_topic[inizio - delta]
                    break
        if not topic: topic = f"Sezione {i + 1}"

        mappa_ent = {}
        for ent in entita:
            ent_start = ent.get("start", -1)
            if char_start <= ent_start < char_end:
                parola = ent.get("word", ent.get("text", ""))
                score = ent.get("score", 0)
                if parola not in mappa_ent or score > mappa_ent[parola]["score"]:
                    mappa_ent[parola] = {"word": parola, "label": ent["label"], "score": score}
        top_ent = sorted(mappa_ent.values(), key=lambda x: x["score"], reverse=True)[:10]

        chunks.append({
            "book_name": nome_libro,
            "chunk_id": i + 1,
            "total_chunks": None,
            "text": testo_chunk,
            "char_start": char_start,
            "char_end": char_end,
            "topic_hint": topic,
            "entities": [{"word": e["word"], "label": e["label"]} for e in top_ent],
        })
    return chunks

def _valida_chunk(chunks: list[dict]) -> list[dict]:
    if not chunks: return chunks
    
    risultato = []
    for chunk in chunks:
        if len(chunk["text"]) > MAX_CHUNK_CHARS:
            paragrafi_chunk = chunk["text"].split("\n\n")
            meta = max(1, len(paragrafi_chunk) // 2)
            parte1 = "\n\n".join(paragrafi_chunk[:meta])
            parte2 = "\n\n".join(paragrafi_chunk[meta:])
            offset_parte2 = chunk["char_start"] + len(parte1) + 2
            
            risultato.append({
                "book_name": chunk["book_name"], "chunk_id": None, "total_chunks": None,
                "text": parte1, "char_start": chunk["char_start"], "char_end": chunk["char_start"] + len(parte1),
                "topic_hint": chunk["topic_hint"] + " (parte 1/2)", "entities": chunk["entities"],
            })
            risultato.append({
                "book_name": chunk["book_name"], "chunk_id": None, "total_chunks": None,
                "text": parte2, "char_start": offset_parte2, "char_end": offset_parte2 + len(parte2),
                "topic_hint": chunk["topic_hint"] + " (parte 2/2)", "entities": [],
            })
        else:
            risultato.append(chunk)

    for idx, chunk in enumerate(risultato):
        chunk["chunk_id"] = idx + 1
        chunk["total_chunks"] = len(risultato)
    return risultato

def _salva_in_locale(output_dir: str, chunks: list[dict], nome_libro: str, num_capitoli_espliciti: int) -> str:
    book_dir = os.path.join(output_dir, nome_libro)
    os.makedirs(book_dir, exist_ok=True)
    
    voci_manifest = []
    for chunk in chunks:
        file_path = os.path.join(book_dir, f"chunk_{chunk['chunk_id']:03d}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(chunk, f, ensure_ascii=False, indent=2)

        voci_manifest.append({
            "chunk_id": chunk["chunk_id"],
            "topic_hint": chunk["topic_hint"],
            "char_start": chunk["char_start"],
            "char_end": chunk["char_end"],
            "num_entities": len(chunk["entities"]),
            "text_length": len(chunk["text"]),
        })

    manifest = {
        "book_name": nome_libro,
        "total_chunks": len(chunks),
        "created_at": datetime.utcnow().isoformat(),
        "explicit_chapters_found": num_capitoli_espliciti,
        "chunks": voci_manifest,
    }
    manifest_path = os.path.join(book_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
        
    print(f"✅ Chunk e Manifest salvati in {book_dir}")
    return manifest_path

def run_semantic_chunker(book_name: str, clean_file_path: str, ner_file_path: str, output_dir: str, progress_cb=None) -> str:
    """Entry point per il backend locale. Restituisce il path del manifest.json generato."""
    try:
        if progress_cb: progress_cb(0, 100, "Caricamento testo ed entità...")
        testo = _carica_testo(clean_file_path)
        entita = _carica_entita(ner_file_path)
        paragrafi = _suddividi_paragrafi(testo)

        if len(paragrafi) < 3:
            chunk_unico = [{
                "book_name": book_name, "chunk_id": 1, "total_chunks": 1,
                "text": testo, "char_start": 0, "char_end": len(testo),
                "topic_hint": "Testo completo",
                "entities": [{"word": e.get("word", e.get("text")), "label": e["label"]} for e in entita[:10]]
            }]
            return _salva_in_locale(output_dir, chunk_unico, book_name, 0)

        confini_espliciti = _trova_marcatori_capitolo(paragrafi)
        if progress_cb: progress_cb(0, len(paragrafi), "Inizio ricerca LLM...")
        confini_llm, mappa_topic = _rileva_confini_llm(paragrafi, entita, progress_cb)
        
        confini_uniti = _unisci_e_filtra_confini(confini_espliciti, confini_llm, paragrafi)
        chunks = _crea_chunk(paragrafi, confini_uniti, mappa_topic, entita, book_name, testo)
        chunks = _valida_chunk(chunks)
        
        if progress_cb: progress_cb(len(paragrafi), len(paragrafi), "Salvataggio chunks in corso...")

        manifest_path = _salva_in_locale(output_dir, chunks, book_name, len(confini_espliciti))
        return manifest_path

    except Exception as e:
        print(f"❌ Errore fatale nel chunking semantico: {e}")
        raise
