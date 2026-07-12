import os
import json
import pytest

# ─── Path al file gold pre-generato ──────────────────────────────────────────
TEST_DIR    = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_FILE = os.path.join(TEST_DIR, "evaluations", "results", "ner_evaluation_results.json")

# ─── Soglie minime accettabili ────────────────────────────────────────────────
MIN_PRECISION = 0.60
MIN_RECALL    = 0.50
MIN_ENTRIES   = 10   # garantisce che il JSON non sia vuoto o parziale


def test_ner_metrics_from_gold():
    """
    Legge il gold standard pre-generato da scripts/generate_ner_gold.py
    e verifica che le metriche NER siano al di sopra delle soglie minime.

    Questo test non chiama nessuna API esterna: è deterministico, gratuito
    e completa in pochi secondi.

    Per aggiornare il gold:
        python3 scripts/generate_ner_gold.py
    """
    if not os.path.exists(RESULTS_FILE):
        pytest.skip(
            f"Gold standard non trovato: {RESULTS_FILE}\n"
            "Esegui prima: python3 scripts/generate_ner_gold.py"
        )

    with open(RESULTS_FILE, "r", encoding="utf-8") as f:
        results = json.load(f)

    if len(results) < MIN_ENTRIES:
        pytest.skip(
            f"Gold standard troppo piccolo ({len(results)} voci, minimo {MIN_ENTRIES}).\n"
            "Esegui: python3 scripts/generate_ner_gold.py"
        )

    # ── Ricalcola le metriche dai campi pre-calcolati nel JSON ───────────────
    global_gold  = 0
    global_local = 0
    global_tp    = 0

    for entry in results:
        global_gold  += len(entry.get("gold_entities_normalized",  []))
        global_local += len(entry.get("local_entities_normalized", []))
        global_tp    += entry.get("true_positives", 0)

    precision = global_tp / global_local if global_local > 0 else 0.0
    recall    = global_tp / global_gold  if global_gold  > 0 else 0.0
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    # ── Stampa riepilogo ─────────────────────────────────────────────────────
    print(f"\n{'='*35}")
    print(f"  RISULTATI GLOBALI NER")
    print(f"{'='*35}")
    print(f"  Campioni valutati          : {len(results)}")
    print(f"  Entità Gold (Claude)       : {global_gold}")
    print(f"  Entità Local (BERT)        : {global_local}")
    print(f"  Match Esatti (TP)          : {global_tp}")
    print(f"  Precision                  : {precision:.2f}  (soglia: ≥ {MIN_PRECISION})")
    print(f"  Recall                     : {recall:.2f}  (soglia: ≥ {MIN_RECALL})")
    print(f"  F1-Score                   : {f1:.2f}")
    print(f"{'='*35}\n")

    # ── Asserzioni ───────────────────────────────────────────────────────────
    assert precision >= MIN_PRECISION, (
        f"Precision troppo bassa: {precision:.2f} (soglia: {MIN_PRECISION})"
    )
    assert recall >= MIN_RECALL, (
        f"Recall troppo bassa: {recall:.2f} (soglia: {MIN_RECALL})"
    )
