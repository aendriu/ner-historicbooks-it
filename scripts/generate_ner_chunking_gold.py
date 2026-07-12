#!/usr/bin/env python3
"""
generate_ner_chunking_gold.py
-------------------------
Script MANUALE per generare il gold standard per il chunking NER.
Legge un campione di blocchi da 2000 caratteri e chiede a Claude di indicare 
in quali indici di blocco cambiano drasticamente i personaggi o l'ambientazione.

Il risultato viene scritto in:
  tests/evaluations/results/ner_chunking_evaluation_results.json
"""

import os
import sys
import json
import argparse

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")
TESTS_PATH   = os.path.join(PROJECT_ROOT, "tests")
RESULTS_DIR  = os.path.join(TESTS_PATH, "evaluations", "results")
RESULTS_FILE = os.path.join(RESULTS_DIR, "ner_chunking_evaluation_results.json")

sys.path.insert(0, BACKEND_PATH)
sys.path.insert(0, TESTS_PATH)

from utils.anthropic_client import AnthropicJudge
from app.pipeline.chunker import (
    _build_chunks_with_ner, 
    _entity_key,
    NER_BOUNDARY_THRESHOLD
)

DATA_DIR = "/home/aendriu/Para/Project/ocr/ocr-rb/ocr-rb-cleaner/data/metadata_cleaned"
NER_DIR  = os.path.join(BACKEND_PATH, "data", "ner")
DEFAULT_BOOK = "promessi_sposi-cleaned.json"
DEFAULT_NER  = "45e11373_promessi_sposi.txt_entities.json"

PROMPT_TEMPLATE = """
Sei un esperto di analisi testuale.
Ti fornirò una serie di blocchi di testo estratti da un libro, numerati da [0] a [{max_idx}].
Ogni blocco ha una dimensione fissa (circa 2000 caratteri).

Il tuo compito è identificare gli indici dei blocchi in cui si verifica un *cambio di scena o di ambientazione significativo*, oppure un *cambio totale dei personaggi in azione*.

Devi rispondere ESATTAMENTE e SOLO con un JSON array di numeri interi (gli indici dei blocchi in cui la scena cambia rispetto ai blocchi precedenti). 
Esempio: [0, 8, 22]

Testo:
{text_numbered}
"""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", type=str, default=DEFAULT_BOOK)
    parser.add_argument("--ner", type=str, default=DEFAULT_NER)
    parser.add_argument("--blocks", type=int, default=50, help="Numero di blocchi da 2000 caratteri da analizzare")
    args = parser.parse_args()

    book_path = os.path.join(DATA_DIR, args.book)
    ner_path  = os.path.join(NER_DIR, args.ner)

    if not os.path.exists(book_path):
        print(f"[ERRORE] File testo non trovato: {book_path}")
        sys.exit(1)
    if not os.path.exists(ner_path):
        print(f"[ERRORE] File NER non trovato: {ner_path}")
        sys.exit(1)

    print(f"[INFO] Caricamento testo e NER...")
    with open(book_path, "r", encoding="utf-8") as f:
        text = json.load(f).get("contenuto", "")
        
    with open(ner_path, "r", encoding="utf-8") as f:
        entities = json.load(f).get("entities", [])

    print(f"[INFO] Taglio del testo in chunk con entità NER assegnate...")
    chunks = _build_chunks_with_ner(args.book, text, entities)
    
    if not chunks:
        print("[ERRORE] Testo vuoto o nessun chunk estratto.")
        sys.exit(1)

    test_chunks = chunks[:args.blocks]
    print(f"[INFO] Selezionati i primi {len(test_chunks)} blocchi (su {len(chunks)} totali).")

    # Costruiamo il testo numerato per Claude
    numbered_lines = []
    for i, c in enumerate(test_chunks):
        numbered_lines.append(f"[BLOCCO {i}]\n{c['text']}\n")
    text_numbered = "\n".join(numbered_lines)

    print(f"[INFO] Chiamata a Claude (Anthropic API)...")
    judge = AnthropicJudge()
    prompt = PROMPT_TEMPLATE.replace("{max_idx}", str(len(test_chunks)-1)).replace("{text_numbered}", text_numbered)

    try:
        gold_boundaries = judge.generate_json_response(
            system_prompt="Sei un sistema automatico. Restituisci SOLO un JSON array di interi.",
            user_prompt=prompt,
        )
    except Exception as e:
        print(f"[ERRORE] API Fallita: {e}")
        sys.exit(1)

    if not isinstance(gold_boundaries, list):
        print("[ERRORE] Claude non ha restituito una lista.")
        sys.exit(1)

    gold_boundaries = [int(x) for x in gold_boundaries if str(x).isdigit()]
    if 0 not in gold_boundaries:
        gold_boundaries.insert(0, 0)
    
    print(f"[OK] Claude ha individuato {len(gold_boundaries)} boundaries: {gold_boundaries}")

    print(f"[INFO] Calcolo boundaries NER locale (Jaccard sulle entità)...")
    local_boundaries = [0]
    for i in range(len(test_chunks) - 1):
        keys_x  = set(_entity_key(e) for e in test_chunks[i]["entities"])
        keys_x1 = set(_entity_key(e) for e in test_chunks[i+1]["entities"])
        common  = len(keys_x & keys_x1)
        if common < NER_BOUNDARY_THRESHOLD:
            local_boundaries.append(i + 1)

    print(f"[OK] Modello locale ha individuato {len(local_boundaries)} boundaries: {local_boundaries}")

    results = {
        "book_name": args.book,
        "blocks_tested": len(test_chunks),
        "gold_boundaries": gold_boundaries,
        "local_boundaries": local_boundaries
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    print(f"\n[OK] Generazione completata! File salvato.")

if __name__ == "__main__":
    main()
