#!/usr/bin/env python3
"""
generate_chunking_gold.py
-------------------------
Script MANUALE per generare il gold standard per i capitoli semantici.

Legge un campione di paragrafi da "I Promessi Sposi" (o un altro libro),
invia i paragrafi numerati a Claude, e calcola i boundaries locali.

Il risultato viene scritto in:
  tests/evaluations/results/chunking_evaluation_results.json
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
RESULTS_FILE = os.path.join(RESULTS_DIR, "chunking_evaluation_results.json")

sys.path.insert(0, BACKEND_PATH)
sys.path.insert(0, TESTS_PATH)

from utils.anthropic_client import AnthropicJudge
from app.pipeline.chunker import (
    split_into_paragraphs, 
    find_semantic_boundaries, 
    find_explicit_chapters
)

DATA_DIR = "/home/aendriu/Para/Project/ocr/ocr-rb/ocr-rb-cleaner/data/metadata_cleaned"
DEFAULT_BOOK = "promessi_sposi-cleaned.json"

PROMPT_TEMPLATE = """
Sei un esperto di analisi testuale e segmentazione semantica.
Ti fornirò una serie di paragrafi estratti da un libro, numerati da [0] a [{max_idx}].
Il tuo compito è identificare i confini dei capitoli semantici, ovvero i punti in cui:
1. Inizia un nuovo capitolo esplicito (es. "Capitolo II").
2. Cambia drasticamente l'argomento, l'ambientazione o il tempo narrativo.

Devi rispondere ESATTAMENTE e SOLO con un JSON array di numeri interi (gli indici dei paragrafi in cui inizia una nuova sezione/capitolo). 
Esempio: [0, 45, 112]

Testo:
{text_numbered}
"""

def main():
    parser = argparse.ArgumentParser(description="Genera il gold standard per il chunking semantico.")
    parser.add_argument("--book", type=str, default=DEFAULT_BOOK, help="Nome del file JSON da usare.")
    parser.add_argument("--paras", type=int, default=150, help="Numero di paragrafi da analizzare (per non superare il context window).")
    args = parser.parse_args()

    filepath = os.path.join(DATA_DIR, args.book)
    if not os.path.exists(filepath):
        print(f"[ERRORE] File non trovato: {filepath}")
        sys.exit(1)

    print(f"[INFO] Caricamento testo da {args.book}...")
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
        text = data.get("contenuto", data.get("text", data.get("content", "")))

    print("[INFO] Estrazione paragrafi...")
    paragraphs = split_into_paragraphs(text)
    
    if not paragraphs:
        print("[ERRORE] Testo vuoto o nessun paragrafo estratto.")
        sys.exit(1)

    # Prendiamo solo un campione di paragrafi (i primi N)
    test_paras = paragraphs[:args.paras]
    print(f"[INFO] Selezionati i primi {len(test_paras)} paragrafi su {len(paragraphs)} totali.")

    # Costruiamo il testo numerato per Claude
    numbered_lines = []
    for i, p in enumerate(test_paras):
        numbered_lines.append(f"[{i}] {p['text']}")
    text_numbered = "\n\n".join(numbered_lines)

    print(f"[INFO] Chiamata a Claude (Anthropic API)...")
    judge = AnthropicJudge()
    prompt = PROMPT_TEMPLATE.replace("{max_idx}", str(len(test_paras)-1)).replace("{text_numbered}", text_numbered)

    try:
        gold_boundaries = judge.generate_json_response(
            system_prompt="Sei un sistema automatico. Restituisci SOLO un JSON array di interi (es. [0, 15, 34]).",
            user_prompt=prompt,
        )
    except Exception as e:
        print(f"[ERRORE] API Fallita: {e}")
        sys.exit(1)

    if not isinstance(gold_boundaries, list):
        print("[ERRORE] La risposta di Claude non è una lista JSON valida.")
        print("Risposta:", gold_boundaries)
        sys.exit(1)

    # Assicuriamoci che siano interi
    gold_boundaries = [int(x) for x in gold_boundaries if isinstance(x, (int, float, str)) and str(x).isdigit()]
    
    # Assicuriamoci che 0 sia incluso
    if 0 not in gold_boundaries:
        gold_boundaries.insert(0, 0)
    
    print(f"[OK] Claude ha individuato {len(gold_boundaries)} boundaries: {gold_boundaries}")

    print(f"[INFO] Esecuzione calcolo vettoriale locale (SentenceTransformers)...")
    sem_bounds = find_semantic_boundaries(test_paras)
    exp_bounds = find_explicit_chapters(test_paras)
    local_boundaries = sorted(list(set([0] + sem_bounds + exp_bounds)))

    print(f"[OK] Modello locale ha individuato {len(local_boundaries)} boundaries: {local_boundaries}")

    # Prepariamo l'oggetto risultato
    results = {
        "book_name": args.book,
        "paragraphs_tested": len(test_paras),
        "gold_boundaries": gold_boundaries,
        "local_boundaries": local_boundaries
    }

    os.makedirs(RESULTS_DIR, exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4)

    print(f"\n[OK] Generazione completata! Risultato salvato in:\n     {RESULTS_FILE}")

if __name__ == "__main__":
    main()
