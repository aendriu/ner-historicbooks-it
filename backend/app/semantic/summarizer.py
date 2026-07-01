import logging

logger = logging.getLogger(__name__)

def generate_chapter_summary(chapter_title: str, chunks_data: list) -> str:
    """
    Funzione temporanea (placeholder) per la generazione dei riassunti.
    In futuro questa fase utilizzerà un SLM (Small Language Model) locale
    al posto di AWS Bedrock/Claude.
    """
    if not chunks_data:
        return ""

    logger.info(f"Generazione riassunto (placeholder) per il capitolo: {chapter_title}")
    
    # Restituisce un testo segnaposto
    return f"⚠️ [Work in Progress] La generazione dei riassunti tramite AI è attualmente in fase di riscrittura per supportare modelli locali (SLM). Questo è un riassunto temporaneo per il capitolo '{chapter_title}'."
