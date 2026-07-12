import os
import json
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import anthropic

logger = logging.getLogger(__name__)

# Carica le variabili d'ambiente (dalla root del progetto)
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.env')
load_dotenv(dotenv_path=env_path)

class AnthropicJudge:
    """Client per interagire con Anthropic e validare la pipeline NLP."""
    
    def __init__(self):
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
        self.api_key = os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key or "inserisci_qui" in self.api_key:
            raise ValueError("ANTHROPIC_API_KEY non configurata nel file .env")
        
        self.client = anthropic.Anthropic(api_key=self.api_key)

    def generate_json_response(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        """Chiama Anthropic forzando una risposta JSON strutturata."""
        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ]
            )
            
            # Estrai il contenuto
            content = "".join([getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text"])
            
            # Prova a parsarla direttamente (assumiamo che il prompt chieda ESATTAMENTE JSON)
            # A volte Claude aggiunge del testo intorno, proviamo a estrarre solo i blocchi {} o []
            start_idx_curl = content.find('{')
            start_idx_sq = content.find('[')
            
            # Find the true start of the JSON (either object or array)
            if start_idx_curl != -1 and start_idx_sq != -1:
                start_idx = min(start_idx_curl, start_idx_sq)
            else:
                start_idx = max(start_idx_curl, start_idx_sq)
                
            if start_idx != -1:
                end_idx_curl = content.rfind('}')
                end_idx_sq = content.rfind(']')
                end_idx = max(end_idx_curl, end_idx_sq)
                
                json_str = content[start_idx:end_idx+1]
                return json.loads(json_str)
                
            return json.loads(content)
            
        except Exception as e:
            print(f"\\n[DEBUG] Errore API Anthropic: {e}")
            if 'content' in locals():
                print(f"[DEBUG] Raw content: {content}")
            logger.error(f"Errore nella chiamata ad Anthropic: {e}")
            return None
