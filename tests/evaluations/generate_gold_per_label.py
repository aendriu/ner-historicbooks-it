#!/usr/bin/env python3
"""
generate_gold_per_label.py
--------------------------
Genera un gold standard NER con Claude per TUTTE le 9 label,
usando testi puliti dalla pipeline (non usati per il training BERT).

Calcola Precision, Recall e F1-Score PER OGNI LABEL.

Output:
  tests/evaluations/results/ner_per_label_gold.json
  tests/evaluations/results/ner_per_label_report.json  (metriche)

Utilizzo:
  python3 tests/evaluations/generate_gold_per_label.py             # default 30 file
  python3 tests/evaluations/generate_gold_per_label.py --files 50  # più campioni
"""

import os
import sys
import json
import random
import argparse
from collections import defaultdict

# ─── Path setup ──────────────────────────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
TEST_DIR     = os.path.dirname(SCRIPT_DIR) if os.path.basename(SCRIPT_DIR) == "evaluations" else SCRIPT_DIR
PROJECT_ROOT = os.path.dirname(TEST_DIR)
BACKEND_PATH = os.path.join(PROJECT_ROOT, "backend")
RESULTS_DIR  = os.path.join(TEST_DIR, "evaluations", "results") if os.path.basename(SCRIPT_DIR) == "evaluations" else os.path.join(SCRIPT_DIR, "results")

sys.path.insert(0, BACKEND_PATH)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tests"))

from utils.anthropic_client import AnthropicJudge
from app.pipeline.ner import get_ner_pipeline

# ─── Testi PULITI dalla pipeline (NON usati per il training) ─────────────────
CLEANED_DIR = os.path.join(BACKEND_PATH, "data", "cleaned")

# Le 9 label del modello BERT
ALL_LABELS = ["PER", "LOC", "ORG", "DATE", "WORK", "EVENT", "TIT", "REL", "FANT"]

# Prompt per Claude che copre tutte e 9 le label
NER_PROMPT_ALL_LABELS = """Sei un esperto annotatore di Named Entity Recognition per testi storici italiani.
Il tuo compito è estrarre TUTTE le entità nominate dal testo seguente, classificandole nelle 9 categorie:

- PER: persona o personaggio specifico (es. "Don Abbondio", "Renzo Tramaglino")
- LOC: luogo fisico, città, nazione, regione (es. "Milano", "Lago di Como")
- ORG: organizzazione, istituzione (es. "Chiesa", "Senato")
- DATE: data, anno, periodo temporale (es. "1628", "il 7 novembre")
- WORK: opera letteraria, artistica (es. "I Promessi Sposi", "Divina Commedia")
- EVENT: evento storico (es. "la peste del 1630", "la battaglia di Lepanto")
- TIT: titolo nobiliare o onorifico (es. "Don", "Marchese", "Fra")
- REL: termine religioso specifico (es. "cappuccino", "convento", "vescovo")
- FANT: personaggio o entità fantastica/mitologica (es. "Ercole", "Minerva")

Rispondi ESATTAMENTE e SOLO con un JSON array valido. Nient'altro.
Formato:
[
  {{"word": "nome esatto dell'entità come appare nel testo", "label": "LABEL"}}
]

Se non trovi nessuna entità di una certa categoria, semplicemente non includerla.
NON inventare entità che non sono nel testo.

Testo:
{text}
"""


# ─── Utilità ─────────────────────────────────────────────────────────────────

def normalize_entity(word: str) -> str:
    """Normalizza per confronto: lowercase, rimuovi punteggiatura."""
    return "".join(c for c in word.lower() if c.isalnum() or c.isspace()).strip()


def get_random_chunk_from_cleaned(filepath: str, min_len: int = 600, max_len: int = 1200) -> str:
    """Estrae un chunk casuale dal corpo del testo (salta primo/ultimo 20%)."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            text = data.get("contenuto", "")
    except Exception:
        return ""

    if len(text) < min_len:
        return ""

    # Salta il primo e l'ultimo 20% per evitare indici e colophon
    start_safe = int(len(text) * 0.2)
    end_safe   = int(len(text) * 0.8) - max_len

    if start_safe >= end_safe:
        start_idx = max(0, len(text) // 2 - max_len // 2)
    else:
        start_idx = random.randint(start_safe, end_safe)

    chunk = text[start_idx : start_idx + max_len]

    # Tronca a confini di parola
    first_space = chunk.find(" ")
    last_space  = chunk.rfind(" ")
    if first_space != -1 and last_space != -1 and first_space < last_space:
        chunk = chunk[first_space + 1 : last_space].strip()

    return chunk


def extract_bert_entities(pipeline, text: str) -> list[dict]:
    """Esegue il BERT locale e restituisce lista di {word, label} normalizzate."""
    raw = pipeline(text)
    entities = []
    current_word = ""
    current_label = ""

    for e in raw:
        label = e.get("entity_group", "")
        word_part = e.get("word", "").replace("##", "")

        if label not in ALL_LABELS:
            if current_word:
                entities.append({"word": normalize_entity(current_word), "label": current_label})
                current_word = ""
            continue

        if e.get("word", "").startswith("##"):
            # Subword: concatena
            current_word += word_part
        else:
            # Nuova entità
            if current_word:
                entities.append({"word": normalize_entity(current_word), "label": current_label})
            current_word = word_part
            current_label = label

    if current_word:
        entities.append({"word": normalize_entity(current_word), "label": current_label})

    # Deduplica
    seen = set()
    deduped = []
    for e in entities:
        key = (e["word"], e["label"])
        if key not in seen and len(e["word"]) >= 2:
            seen.add(key)
            deduped.append(e)

    return deduped


def _fuzzy_match(a: str, b: str) -> bool:
    """Confronto fuzzy: match se una stringa contiene l'altra (dopo collasso spazi).

    Gestisce artefatti OCR come:
      - 'o riandò' ↔ 'o riandò furioso' (substring)
      - 'mania' ↔ 'u mania' (substring)
      - 'ludovico a riosto' ↔ 'ludovico ariosto' (spazi OCR)
    """
    # Normalizza spazi multipli
    a_clean = " ".join(a.split())
    b_clean = " ".join(b.split())

    if a_clean == b_clean:
        return True

    # Substring: se uno contiene l'altro (minimo 3 char per evitare falsi positivi)
    if len(a_clean) >= 3 and len(b_clean) >= 3:
        if a_clean in b_clean or b_clean in a_clean:
            return True

    # Collassa tutti gli spazi e riprova (per "A riosto" vs "Ariosto")
    a_nospace = a_clean.replace(" ", "")
    b_nospace = b_clean.replace(" ", "")
    if a_nospace == b_nospace:
        return True

    return False


def compute_per_label_metrics(gold_entities: list[dict], bert_entities: list[dict]) -> dict:
    """Calcola TP, FP, FN per ogni label tra gold e BERT.

    Usa fuzzy matching (substring + collasso spazi) per gestire
    le differenze introdotte dagli artefatti OCR.
    """
    # Costruisci liste per label
    gold_by_label = defaultdict(list)
    bert_by_label = defaultdict(list)

    for e in gold_entities:
        if e.get("label") in ALL_LABELS:
            gold_by_label[e["label"]].append(normalize_entity(e["word"]))

    for e in bert_entities:
        if e.get("label") in ALL_LABELS:
            bert_by_label[e["label"]].append(e["word"])  # già normalizzato

    metrics = {}
    for label in ALL_LABELS:
        gold_list = gold_by_label.get(label, [])
        bert_list = bert_by_label.get(label, [])

        # Fuzzy matching: per ogni gold, cerca un match in bert (e viceversa)
        gold_matched = set()
        bert_matched = set()

        for gi, g in enumerate(gold_list):
            for bi, b in enumerate(bert_list):
                if bi not in bert_matched and _fuzzy_match(g, b):
                    gold_matched.add(gi)
                    bert_matched.add(bi)
                    break

        tp = len(gold_matched)
        fn = len(gold_list) - tp
        fp = len(bert_list) - len(bert_matched)

        metrics[label] = {"tp": tp, "fp": fp, "fn": fn}

    return metrics


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Genera gold NER per tutte le 9 label.")
    parser.add_argument("--files", type=int, default=30, help="Numero di file da campionare (default: 30)")
    parser.add_argument("--seed", type=int, default=42, help="Seed random per riproducibilità")
    parser.add_argument("--append", action="store_true", help="Appendi ai risultati esistenti (salta file già processati)")
    args = parser.parse_args()

    random.seed(args.seed)

    if not os.path.exists(CLEANED_DIR):
        print(f"[ERRORE] Cartella testi puliti non trovata: {CLEANED_DIR}")
        sys.exit(1)

    # Usa solo i file *-cleaned.json (output della pipeline di pulizia)
    all_files = [f for f in os.listdir(CLEANED_DIR) if f.endswith("-cleaned.json")]
    if not all_files:
        print("[ERRORE] Nessun file -cleaned.json trovato.")
        sys.exit(1)

    # ── Carica risultati esistenti se --append ────────────────────────────────
    gold_path = os.path.join(RESULTS_DIR, "ner_per_label_gold.json")
    existing_results = []
    already_done = set()

    if args.append and os.path.exists(gold_path):
        with open(gold_path, "r", encoding="utf-8") as f:
            existing_results = json.load(f)
        already_done = {r["filename"] for r in existing_results}
        print(f"[INFO] Append: {len(existing_results)} campioni esistenti, {len(already_done)} file già processati.")

    # Filtra file già processati
    available_files = [f for f in all_files if f not in already_done]
    max_files = min(len(available_files), args.files)
    files_to_process = random.sample(available_files, max_files)

    print(f"[INFO] Caricamento modelli...")
    judge    = AnthropicJudge()
    pipeline = get_ner_pipeline()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    results = list(existing_results)  # parti dai risultati esistenti se --append
    # Contatori globali per label (ricalcolati da zero su TUTTI i risultati alla fine)
    global_metrics = {label: {"tp": 0, "fp": 0, "fn": 0} for label in ALL_LABELS}

    print(f"[INFO] Generazione gold per {max_files} NUOVI file (tutte le 9 label)...\n")

    for i, filename in enumerate(files_to_process):
        filepath = os.path.join(CLEANED_DIR, filename)
        test_text = get_random_chunk_from_cleaned(filepath)

        if len(test_text) < 100:
            print(f"[{i+1}/{max_files}] {filename} — SALTATO (testo troppo corto)")
            continue

        print(f"[{i+1}/{max_files}] {filename[:60]}... ", end="", flush=True)

        # 1. Gold Standard (Claude) — tutte le 9 label
        prompt = NER_PROMPT_ALL_LABELS.replace("{text}", test_text)
        try:
            gold_entities = judge.generate_json_response(
                system_prompt="Sei un annotatore NLP esperto in letteratura italiana storica. Rispondi SOLO con JSON valido.",
                user_prompt=prompt,
            )
        except Exception as e:
            print(f"ERRORE API ({e})")
            continue

        if not gold_entities or not isinstance(gold_entities, list):
            print("FALLITO (risposta Claude non valida)")
            continue

        # Filtra solo label valide
        gold_entities = [e for e in gold_entities if isinstance(e, dict) and e.get("label") in ALL_LABELS]

        # 2. BERT locale — tutte le label
        bert_entities = extract_bert_entities(pipeline, test_text)

        # 3. Metriche per label su questo campione
        sample_metrics = compute_per_label_metrics(gold_entities, bert_entities)

        # Accumula globali
        for label in ALL_LABELS:
            global_metrics[label]["tp"] += sample_metrics[label]["tp"]
            global_metrics[label]["fp"] += sample_metrics[label]["fp"]
            global_metrics[label]["fn"] += sample_metrics[label]["fn"]

        results.append({
            "filename": filename,
            "chunk_text": test_text,
            "gold_entities": gold_entities,
            "bert_entities": bert_entities,
            "per_label_metrics": sample_metrics,
        })

        n_gold = len(gold_entities)
        n_bert = len(bert_entities)
        total_tp = sum(sample_metrics[l]["tp"] for l in ALL_LABELS)
        print(f"Gold={n_gold}, BERT={n_bert}, TP={total_tp}")

    # ── Ricalcola metriche su TUTTI i risultati (esistenti + nuovi) ────────────
    global_metrics = {label: {"tp": 0, "fp": 0, "fn": 0} for label in ALL_LABELS}
    for entry in results:
        m = compute_per_label_metrics(entry["gold_entities"], entry["bert_entities"])
        for label in ALL_LABELS:
            global_metrics[label]["tp"] += m[label]["tp"]
            global_metrics[label]["fp"] += m[label]["fp"]
            global_metrics[label]["fn"] += m[label]["fn"]

    report = {"per_label": {}, "aggregate": {}}

    total_tp = total_fp = total_fn = 0

    print(f"\n{'='*65}")
    print(f"  RISULTATI PER LABEL — F1-Score")
    print(f"{'='*65}")
    print(f"  {'Label':<8} {'Precision':>10} {'Recall':>10} {'F1':>10} {'TP':>6} {'FP':>6} {'FN':>6}")
    print(f"  {'-'*58}")

    for label in ALL_LABELS:
        tp = global_metrics[label]["tp"]
        fp = global_metrics[label]["fp"]
        fn = global_metrics[label]["fn"]

        total_tp += tp
        total_fp += fp
        total_fn += fn

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall    = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

        report["per_label"][label] = {
            "precision": round(precision, 3),
            "recall":    round(recall, 3),
            "f1":        round(f1, 3),
            "tp": tp, "fp": fp, "fn": fn,
        }

        print(f"  {label:<8} {precision:>10.3f} {recall:>10.3f} {f1:>10.3f} {tp:>6} {fp:>6} {fn:>6}")

    # Aggregate (micro-average)
    agg_precision = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0
    agg_recall    = total_tp / (total_tp + total_fn) if (total_tp + total_fn) > 0 else 0.0
    agg_f1        = 2 * agg_precision * agg_recall / (agg_precision + agg_recall) if (agg_precision + agg_recall) > 0 else 0.0

    report["aggregate"] = {
        "precision": round(agg_precision, 3),
        "recall":    round(agg_recall, 3),
        "f1":        round(agg_f1, 3),
        "total_tp": total_tp, "total_fp": total_fp, "total_fn": total_fn,
        "total_samples": len(results),
    }

    print(f"  {'-'*58}")
    print(f"  {'TOTAL':<8} {agg_precision:>10.3f} {agg_recall:>10.3f} {agg_f1:>10.3f} {total_tp:>6} {total_fp:>6} {total_fn:>6}")
    print(f"{'='*65}")
    print(f"  Campioni valutati: {len(results)}")
    print(f"{'='*65}\n")

    # ── Salvataggio ──────────────────────────────────────────────────────────
    gold_path   = os.path.join(RESULTS_DIR, "ner_per_label_gold.json")
    report_path = os.path.join(RESULTS_DIR, "ner_per_label_report.json")

    with open(gold_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"[OK] Gold salvato in:\n     {gold_path}")
    print(f"[OK] Report salvato in:\n     {report_path}\n")


if __name__ == "__main__":
    main()
