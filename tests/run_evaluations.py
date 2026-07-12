import pytest
import sys
import os

if __name__ == "__main__":
    # Aggiungi backend al path
    backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend'))
    if backend_path not in sys.path:
        sys.path.insert(0, backend_path)
    
    # Esegue i test nella cartella evaluations
    eval_dir = os.path.join(os.path.dirname(__file__), 'evaluations')
    
    print("Avvio del framework di valutazione scientifica (LLM-as-a-Judge)...\n")
    sys.exit(pytest.main(["-v", "-s", eval_dir]))
