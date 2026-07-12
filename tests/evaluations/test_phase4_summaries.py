import os
import sys
import pytest
import logging

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../'))
sys.path.insert(0, os.path.join(project_root, 'backend'))
sys.path.insert(0, os.path.join(project_root, 'test'))

from utils.anthropic_client import AnthropicJudge

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """
Sei un valutatore oggettivo di riassunti. Ti verrà fornito un "Testo Originale" storico e un "Riassunto" generato da un altro modello.
Valuta il riassunto assegnando uno score da 1 a 5 per tre parametri:
1. coherence_score (1-5): Il riassunto ha senso ed è scritto bene?
2. hallucination_score (1-5): Il riassunto inventa fatti NON presenti nel testo? (5 = nessuna invenzione, 1 = tutto inventato)
3. entity_recall_score (1-5): Il riassunto menziona i personaggi e luoghi chiave del testo originale?

Rispondi SOLO con JSON:
{
  "coherence_score": int,
  "hallucination_score": int,
  "entity_recall_score": int,
  "feedback": "stringa"
}

Testo Originale:
{original}

Riassunto da valutare:
{summary}
"""

def test_summary_quality():
    """Usa Anthropic per valutare la qualità di un riassunto generato localmente."""
    
    test_original = (
        "Renzo, salito al palazzotto, non trovò nessuno ad attenderlo. "
        "Le guardie erano assenti, e solo il vecchio servitore Pietro stava pulendo l'ingresso. "
        "Pietro gli disse che Don Rodrigo era partito per Milano il giorno prima."
    )
    # Fingiamo che questo sia il riassunto prodotto dal nostro Qwen locale
    test_summary = "Renzo entra nel palazzotto incustodito e viene informato da Pietro che Don Rodrigo si è recato a Milano."
    
    judge = AnthropicJudge()
    prompt = SUMMARY_PROMPT.replace("{original}", test_original).replace("{summary}", test_summary)
    
    response = judge.generate_json_response(
        system_prompt="Sei un severo professore di letteratura.",
        user_prompt=prompt
    )
    
    assert response is not None, "Anthropic non ha restituito JSON"
    assert "coherence_score" in response, "Chiave mancante"
    
    print("\n--- RISULTATI SUMMARIZATION ---")
    print(f"Coerenza: {response['coherence_score']}/5")
    print(f"Assenza di Allucinazioni: {response['hallucination_score']}/5")
    print(f"Ritenzione Entità: {response['entity_recall_score']}/5")
    print(f"Feedback: {response['feedback']}")
    
    # Assicuriamoci che gli score siano accettabili per la tesi (minimo 3/5)
    assert response["coherence_score"] >= 3
    assert response["hallucination_score"] >= 3
    assert response["entity_recall_score"] >= 3
