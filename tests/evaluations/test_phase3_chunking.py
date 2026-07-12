import os
import json
import pytest

TEST_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_FILE = os.path.join(TEST_DIR, "evaluations", "results", "chunking_evaluation_results.json")

# Tolleranza: se il nostro modello taglia entro ±2 paragrafi rispetto a Claude, lo consideriamo corretto.
TOLERANCE_WINDOW = 2
MIN_PRECISION = 0.45
MIN_RECALL    = 0.60

def is_match(local_b: int, gold_boundaries: list[int], tolerance: int) -> bool:
    """Verifica se il boundary locale è vicino a uno dei gold boundaries."""
    for g in gold_boundaries:
        if abs(local_b - g) <= tolerance:
            return True
    return False

def test_semantic_chunking_boundaries():
    """
    Legge il gold standard generato da scripts/generate_chunking_gold.py
    e calcola precision e recall dei confini dei capitoli semantici.
    """
    if not os.path.exists(RESULTS_FILE):
        pytest.skip(
            f"Gold standard non trovato: {RESULTS_FILE}\n"
            "Esegui prima: python3 scripts/generate_chunking_gold.py"
        )

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)

    gold = results.get("gold_boundaries", [])
    local = results.get("local_boundaries", [])

    if not gold or not local:
        pytest.fail("I dati JSON di valutazione sono vuoti o invalidi.")

    # Calcolo True Positives (dal punto di vista Locale -> Gold per Precision)
    tp_precision = sum(1 for b in local if is_match(b, gold, TOLERANCE_WINDOW))
    
    # Calcolo True Positives (dal punto di vista Gold -> Locale per Recall)
    # È leggermente diverso: quanti gold boundaries sono stati "coperti" da almeno un locale?
    tp_recall = sum(1 for g in gold if is_match(g, local, TOLERANCE_WINDOW))

    precision = tp_precision / len(local) if local else 0.0
    recall    = tp_recall / len(gold) if gold else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    print(f"\n{'='*35}")
    print(f"  RISULTATI CHUNKING SEMANTICO")
    print(f"{'='*35}")
    print(f"  Libro analizzato           : {results.get('book_name')}")
    print(f"  Paragrafi testati          : {results.get('paragraphs_tested')}")
    print(f"  Tolleranza                 : ±{TOLERANCE_WINDOW} paragrafi")
    print(f"  Capitoli Gold (Claude)     : {len(gold)}")
    print(f"  Capitoli Local (Vector)    : {len(local)}")
    print(f"  Precision                  : {precision:.2f}  (soglia: ≥ {MIN_PRECISION})")
    print(f"  Recall                     : {recall:.2f}  (soglia: ≥ {MIN_RECALL})")
    print(f"  F1-Score                   : {f1:.2f}")
    print(f"{'='*35}\n")

    assert precision >= MIN_PRECISION, f"Precision troppo bassa: {precision:.2f}"
    assert recall >= MIN_RECALL, f"Recall troppo bassa: {recall:.2f}"
