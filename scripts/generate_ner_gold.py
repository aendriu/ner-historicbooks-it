#!/usr/bin/env python3
"""
generate_ner_gold.py
--------------------
Script MANUALE per generare (o aggiornare) il gold standard NER.

Esegue due inferenze sullo stesso frammento di testo:
  1. Claude Sonnet (Gold Standard via API Anthropic)
  2. BERT fine-tuned locale (aendriu/bert-ner-italian-historical)

Il risultato viene scritto in:
  test/evaluations/results/ner_evaluation_results.json

Questo file va poi versionato su git e viene letto da:
  test/evaluations/test_phase2_ner.py   (pytest, zero costi API)

Utilizzo:
  python3 scripts/generate_ner_gold.py            # tutti i file disponibili (max 100)
  python3 scripts/generate_ner_gold.py --files 20 # campione ridotto
"""

import os
import sys
import json
import random
import argparse

# ─── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")
TEST_PATH    = os.path.join(PROJECT_ROOT, "tests")
RESULTS_DIR  = os.path.join(TEST_PATH, "evaluations", "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "ner_evaluation_results.json")

sys.path.insert(0, BACKEND_PATH)
sys.path.insert(0, TEST_PATH)

from utils.anthropic_client import AnthropicJudge
from app.pipeline.ner import get_ner_pipeline

# ─── Dati ────────────────────────────────────────────────────────────────────
DATA_DIR = "/home/aendriu/Para/Project/ocr/ocr-rb/ocr-rb-cleaner/data/metadata_cleaned"

NER_PROMPT = """
Sei un esperto annotatore di Named Entity Recognition per testi storici italiani.
Il tuo compito è estrarre Personaggi (PER) e Luoghi (LOC) dal testo seguente.
Devi rispondere ESATTAMENTE e SOLO con un JSON array di oggetti, con questo formato:
[
  {"word": "nome dell'entità", "label": "PER oppure LOC"}
]

Regole:
1. PER: solo persone o personaggi specifici.
2. LOC: solo luoghi fisici, città, nazioni.
3. Rispondi solo con l'array JSON valido, nient'altro.

Testo:
{text}
"""

# ─── Utilità ─────────────────────────────────────────────────────────────────

def normalize_entity(word: str) -> str:
    """Normalizza la parola per il confronto (rimuove punteggiatura e lowercase)."""
    return "".join(c for c in word.lower() if c.isalnum() or c.isspace()).strip()


def get_random_chunk_from_file(filepath: str, min_len: int = 500, max_len: int = 1000) -> str:
    """Estrae un chunk casuale dal centro del testo (salta indici e prefazioni)."""
    with open(filepath, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
            text = data.get("contenuto", "")
        except Exception:
            return ""

    if len(text) < min_len:
        return text

    start_safe = int(len(text) * 0.2)
    end_safe   = len(text) - max_len

    if start_safe >= end_safe:
        start_idx = max(0, len(text) // 2 - max_len // 2)
    else:
        start_idx = random.randint(start_safe, end_safe)

    chunk = text[start_idx : start_idx + max_len]
    first_space = chunk.find(" ")
    last_space  = chunk.rfind(" ")
    if first_space != -1 and last_space != -1 and first_space < last_space:
        chunk = chunk[first_space:last_space].strip()

    return chunk


def extract_local_entities(pipeline, text: str) -> set:
    """Esegue il modello BERT locale e restituisce un set di entità normalizzate."""
    raw = pipeline(text)
    words = []
    current = ""
    for e in raw:
        if e["entity_group"] in ("PER", "LOC"):
            word = e["word"].replace("##", "")
            if current and not e["word"].startswith("##"):
                words.append(normalize_entity(current))
                current = word
            else:
                current += word
    if current:
        words.append(normalize_entity(current))
    return set(words)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera il gold standard NER.")
    parser.add_argument(
        "--files", type=int, default=100,
        help="Numero massimo di file da campionare (default: 100)"
    )
    args = parser.parse_args()

    if not os.path.exists(DATA_DIR):
        print(f"[ERRORE] Cartella dati non trovata: {DATA_DIR}")
        sys.exit(1)

    all_files = [f for f in os.listdir(DATA_DIR) if f.endswith(".json")]
    if not all_files:
        print("[ERRORE] Nessun file JSON trovato.")
        sys.exit(1)

    max_files = min(len(all_files), args.files)
    files_to_process = random.sample(all_files, max_files)

    print(f"[INFO] Caricamento modelli...")
    judge    = AnthropicJudge()
    pipeline = get_ner_pipeline()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    results = []
    global_gold  = 0
    global_local = 0
    global_tp    = 0

    print(f"[INFO] Generazione gold standard su {max_files} file...\n")

    for i, filename in enumerate(files_to_process):
        filepath  = os.path.join(DATA_DIR, filename)
        test_text = get_random_chunk_from_file(filepath)

        if len(test_text) < 100:
            print(f"[{i+1}/{max_files}] {filename} — SALTATO (testo troppo corto)")
            continue

        print(f"[{i+1}/{max_files}] {filename} ... ", end="", flush=True)

        # 1. Gold Standard (Claude)
        prompt = NER_PROMPT.replace("{text}", test_text)
        try:
            gold_entities = judge.generate_json_response(
                system_prompt="Sei un annotatore NLP preciso e rispondi solo in JSON.",
                user_prompt=prompt,
            )
        except Exception as e:
            print(f"ERRORE API ({e})")
            continue

        if not gold_entities or not isinstance(gold_entities, list):
            print("FALLITO (risposta Anthropic non valida)")
            continue

        gold_set = set(
            normalize_entity(e["word"])
            for e in gold_entities
            if isinstance(e, dict) and e.get("label") in ("PER", "LOC")
        )

        # 2. Modello locale (BERT)
        local_set = extract_local_entities(pipeline, test_text)

        tp = len(gold_set & local_set)
        global_gold  += len(gold_set)
        global_local += len(local_set)
        global_tp    += tp

        results.append({
            "filename":                   filename,
            "chunk_text":                 test_text,
            "gold_entities_raw":          gold_entities,
            "gold_entities_normalized":   list(gold_set),
            "local_entities_normalized":  list(local_set),
            "true_positives":             tp,
        })

        print(f"Gold={len(gold_set)}, Local={len(local_set)}, Match={tp}")

    # ── Salvataggio ──────────────────────────────────────────────────────────
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    # ── Riepilogo ────────────────────────────────────────────────────────────
    precision = global_tp / global_local if global_local > 0 else 0.0
    recall    = global_tp / global_gold  if global_gold  > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    print(f"\n{'='*35}")
    print(f"  RISULTATI GOLD GENERATION")
    print(f"{'='*35}")
    print(f"  File processati            : {len(results)}")
    print(f"  Entità Gold (Claude)       : {global_gold}")
    print(f"  Entità Local (BERT)        : {global_local}")
    print(f"  Match Esatti (TP)          : {global_tp}")
    print(f"  Precision                  : {precision:.2f}")
    print(f"  Recall                     : {recall:.2f}")
    print(f"  F1-Score                   : {f1:.2f}")
    print(f"{'='*35}")
    print(f"\n[OK] Risultati salvati in:\n     {RESULTS_FILE}\n")


if __name__ == "__main__":
    main()
