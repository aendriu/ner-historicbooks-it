#!/usr/bin/env python3
"""
generate_synthetic_gold.py
--------------------------
Genera frasi sintetiche di letteratura italiana storica tramite Claude,
le annota (gold), le fa analizzare dal BERT locale, e appende i risultati
al corpus gold esistente.

Ogni batch genera 10 frasi focalizzate su un mix di label, con enfasi
sulle categorie sotto-rappresentate (EVENT, TIT, REL, FANT).

Utilizzo:
  python3 tests/evaluations/generate_synthetic_gold.py              # default 144
  python3 tests/evaluations/generate_synthetic_gold.py --count 50   # meno frasi
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

ALL_LABELS = ["PER", "LOC", "ORG", "DATE", "WORK", "EVENT", "TIT", "REL", "FANT"]

# ── Profili di generazione: ogni profilo enfatizza certe label ────────────────
GENERATION_PROFILES = [
    {
        "focus": "EVENT + DATE + PER",
        "description": "battaglie, guerre, trattati, eventi storici con date precise",
        "required_labels": ["EVENT", "DATE", "PER", "LOC"],
    },
    {
        "focus": "TIT + PER + REL",
        "description": "nobili, prelati, titoli onorifici, cardinali, vescovi, frati",
        "required_labels": ["TIT", "PER", "REL", "LOC"],
    },
    {
        "focus": "FANT + WORK + PER",
        "description": "miti, divinità, creature fantastiche, opere letterarie",
        "required_labels": ["FANT", "WORK", "PER"],
    },
    {
        "focus": "ORG + LOC + DATE",
        "description": "istituzioni, repubbliche, senati, concili, accademie",
        "required_labels": ["ORG", "LOC", "DATE", "PER"],
    },
    {
        "focus": "REL + EVENT + TIT",
        "description": "concili, eresie, ordini religiosi, cerimonie, investiture",
        "required_labels": ["REL", "EVENT", "TIT", "PER"],
    },
    {
        "focus": "FANT + EVENT + LOC",
        "description": "imprese mitologiche, viaggi leggendari, luoghi fantastici",
        "required_labels": ["FANT", "EVENT", "LOC", "PER"],
    },
]

SYNTH_PROMPT = """Genera esattamente {batch_size} frasi DIVERSE in italiano, nello stile della letteratura storica italiana (XVI-XIX secolo).

FOCUS TEMATICO: {focus}
Contesto: {description}

OGNI frase deve:
- Essere lunga 80-200 parole
- Contenere almeno un'entità per ognuna di queste categorie: {required_labels}
- Essere stilisticamente coerente con la letteratura italiana storica
- NON essere una citazione reale, ma una frase inventata nello stile appropriato

Le 9 categorie di entità:
- PER: persona (es. "Lorenzo de' Medici")
- LOC: luogo (es. "Firenze", "il Tevere")
- ORG: organizzazione (es. "la Repubblica", "il Senato")
- DATE: data (es. "nel 1527", "il terzo giorno di maggio")
- WORK: opera (es. "il Decameron", "la Gerusalemme Liberata")
- EVENT: evento storico (es. "la battaglia di Lepanto", "il Sacco di Roma")
- TIT: titolo (es. "il Marchese", "Sua Santità", "Fra")
- REL: termine religioso (es. "cappuccino", "convento", "vescovo")
- FANT: personaggio fantastico/mitologico (es. "Ercole", "Minerva", "il Minotauro")

Rispondi SOLO con un JSON array. Per ogni frase, fornisci il testo e le annotazioni:
[
  {{
    "text": "La frase generata...",
    "entities": [
      {{"word": "parola esatta dalla frase", "label": "LABEL"}}
    ]
  }}
]
"""


def normalize_entity(word: str) -> str:
    return "".join(c for c in word.lower() if c.isalnum() or c.isspace()).strip()


def _fuzzy_match(a: str, b: str) -> bool:
    a_clean = " ".join(a.split())
    b_clean = " ".join(b.split())
    if a_clean == b_clean:
        return True
    if len(a_clean) >= 3 and len(b_clean) >= 3:
        if a_clean in b_clean or b_clean in a_clean:
            return True
    a_nospace = a_clean.replace(" ", "")
    b_nospace = b_clean.replace(" ", "")
    if a_nospace == b_nospace:
        return True
    return False


def extract_bert_entities(pipeline, text: str) -> list[dict]:
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
            current_word += word_part
        else:
            if current_word:
                entities.append({"word": normalize_entity(current_word), "label": current_label})
            current_word = word_part
            current_label = label
    if current_word:
        entities.append({"word": normalize_entity(current_word), "label": current_label})

    seen = set()
    deduped = []
    for e in entities:
        key = (e["word"], e["label"])
        if key not in seen and len(e["word"]) >= 2:
            seen.add(key)
            deduped.append(e)
    return deduped


def compute_per_label_metrics(gold_entities, bert_entities):
    gold_by_label = defaultdict(list)
    bert_by_label = defaultdict(list)

    for e in gold_entities:
        if e.get("label") in ALL_LABELS:
            gold_by_label[e["label"]].append(normalize_entity(e["word"]))
    for e in bert_entities:
        if e.get("label") in ALL_LABELS:
            bert_by_label[e["label"]].append(e["word"])

    metrics = {}
    for label in ALL_LABELS:
        gold_list = gold_by_label.get(label, [])
        bert_list = bert_by_label.get(label, [])

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=144, help="Numero di frasi sintetiche (default: 144)")
    parser.add_argument("--batch-size", type=int, default=5, help="Frasi per chiamata Claude (default: 5)")
    args = parser.parse_args()

    print("[INFO] Caricamento modelli...")
    judge    = AnthropicJudge()
    pipeline = get_ner_pipeline()

    os.makedirs(RESULTS_DIR, exist_ok=True)

    # ── Carica risultati reali esistenti ─────────────────────────────────────
    gold_path = os.path.join(RESULTS_DIR, "ner_per_label_gold.json")
    existing_results = []
    if os.path.exists(gold_path):
        with open(gold_path, "r", encoding="utf-8") as f:
            existing_results = json.load(f)
        print(f"[INFO] Trovati {len(existing_results)} campioni reali esistenti.")

    # ── Genera frasi sintetiche a batch ──────────────────────────────────────
    total_batches = (args.count + args.batch_size - 1) // args.batch_size
    synthetic_results = []
    generated = 0

    print(f"[INFO] Generazione di {args.count} frasi sintetiche ({total_batches} batch da {args.batch_size})...\n")

    for batch_idx in range(total_batches):
        if generated >= args.count:
            break

        remaining = min(args.batch_size, args.count - generated)
        profile = GENERATION_PROFILES[batch_idx % len(GENERATION_PROFILES)]

        print(f"[Batch {batch_idx+1}/{total_batches}] Focus: {profile['focus']} ({remaining} frasi)... ", end="", flush=True)

        prompt = SYNTH_PROMPT.format(
            batch_size=remaining,
            focus=profile["focus"],
            description=profile["description"],
            required_labels=", ".join(profile["required_labels"]),
        )

        try:
            response = judge.generate_json_response(
                system_prompt="Sei un generatore di frasi per NER training. Rispondi SOLO con JSON valido. NON usare blocchi ```json```, scrivi direttamente l'array JSON.",
                user_prompt=prompt,
                max_tokens=8192,
            )
        except Exception as e:
            print(f"ERRORE ({e})")
            continue

        if not response or not isinstance(response, list):
            print("FALLITO (risposta non valida)")
            continue

        batch_tp = 0
        for item in response:
            if not isinstance(item, dict) or "text" not in item or "entities" not in item:
                continue

            text = item["text"]
            gold_entities = [e for e in item["entities"] if isinstance(e, dict) and e.get("label") in ALL_LABELS]

            if len(text) < 50 or len(gold_entities) == 0:
                continue

            # Esegui BERT
            bert_entities = extract_bert_entities(pipeline, text)
            sample_metrics = compute_per_label_metrics(gold_entities, bert_entities)
            sample_tp = sum(sample_metrics[l]["tp"] for l in ALL_LABELS)
            batch_tp += sample_tp

            synthetic_results.append({
                "filename": f"SYNTHETIC_batch{batch_idx+1}_{generated+1}",
                "chunk_text": text,
                "gold_entities": gold_entities,
                "bert_entities": bert_entities,
                "per_label_metrics": sample_metrics,
                "is_synthetic": True,
            })
            generated += 1

        print(f"OK — {len(response)} frasi, TP totali={batch_tp}")

    print(f"\n[INFO] Generate {len(synthetic_results)} frasi sintetiche valide.")

    # ── Unisci e ricalcola ───────────────────────────────────────────────────
    all_results = existing_results + synthetic_results
    global_metrics = {label: {"tp": 0, "fp": 0, "fn": 0} for label in ALL_LABELS}

    for entry in all_results:
        m = compute_per_label_metrics(entry["gold_entities"], entry["bert_entities"])
        for label in ALL_LABELS:
            global_metrics[label]["tp"] += m[label]["tp"]
            global_metrics[label]["fp"] += m[label]["fp"]
            global_metrics[label]["fn"] += m[label]["fn"]

    # ── Stampa risultati ─────────────────────────────────────────────────────
    report = {"per_label": {}, "aggregate": {}, "breakdown": {
        "real_samples": len(existing_results),
        "synthetic_samples": len(synthetic_results),
        "total_samples": len(all_results),
    }}

    total_tp = total_fp = total_fn = 0

    print(f"\n{'='*65}")
    print(f"  RISULTATI COMBINATI (reali + sintetici) — F1-Score")
    print(f"  {len(existing_results)} reali + {len(synthetic_results)} sintetici = {len(all_results)} totali")
    print(f"{'='*65}")
    print(f"  {'Label':<8} {'Prec':>8} {'Recall':>8} {'F1':>8} {'TP':>5} {'FP':>5} {'FN':>5}")
    print(f"  {'-'*50}")

    for label in ALL_LABELS:
        tp = global_metrics[label]["tp"]; fp = global_metrics[label]["fp"]; fn = global_metrics[label]["fn"]
        total_tp += tp; total_fp += fp; total_fn += fn
        p = tp / (tp + fp) if tp + fp else 0
        r = tp / (tp + fn) if tp + fn else 0
        f = 2 * p * r / (p + r) if p + r else 0
        report["per_label"][label] = {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3), "tp": tp, "fp": fp, "fn": fn}
        print(f"  {label:<8} {p:>8.3f} {r:>8.3f} {f:>8.3f} {tp:>5} {fp:>5} {fn:>5}")

    p = total_tp / (total_tp + total_fp) if total_tp + total_fp else 0
    r = total_tp / (total_tp + total_fn) if total_tp + total_fn else 0
    f = 2 * p * r / (p + r) if p + r else 0
    report["aggregate"] = {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f, 3),
                           "total_tp": total_tp, "total_fp": total_fp, "total_fn": total_fn}

    print(f"  {'-'*50}")
    print(f"  {'TOTAL':<8} {p:>8.3f} {r:>8.3f} {f:>8.3f} {total_tp:>5} {total_fp:>5} {total_fn:>5}")
    print(f"{'='*65}\n")

    # ── Salvataggio ──────────────────────────────────────────────────────────
    with open(gold_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)

    report_path = os.path.join(RESULTS_DIR, "ner_per_label_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print(f"[OK] Gold salvato ({len(all_results)} campioni): {gold_path}")
    print(f"[OK] Report: {report_path}\n")


if __name__ == "__main__":
    main()
