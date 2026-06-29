import os
import sqlite3
import json
import random
import re
import time
import boto3
from concurrent.futures import ThreadPoolExecutor

# Configurazione
DB_PATH = "../backend/historicbooks.db"
MODEL_ID = "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"
MAX_PARAGRAPHS = 200  # Numero di frasi da campionare (per test veloce)
TRAIN_RATIO = 0.8
VAL_RATIO = 0.1
TEST_RATIO = 0.1
OUTPUT_DIR = "data"

bedrock = boto3.client("bedrock-runtime", region_name="eu-central-1")

# Dizionario per la Data Augmentation
AUGMENT_DICT = {
    "PER": ["Petrarca", "Boccaccio", "Ariosto", "Torquato Tasso", "Machiavelli", "Lorenzo de' Medici", "Beatrice", "Laura", "Federico Barbarossa", "Carlo Magno"],
    "LOC": ["Venezia", "Napoli", "Milano", "Roma", "Gerusalemme", "Costantinopoli", "Siena", "Pisa", "Mantova", "Ferrara"],
    "ORG": ["Chiesa Cattolica", "Repubblica di Venezia", "Signoria di Firenze", "Stato della Chiesa", "Impero Romano", "Cavalieri Templari"],
    "WORK": ["Decameron", "Orlando Furioso", "Gerusalemme Liberata", "Il Principe", "Canzoniere", "Eneide"],
    "DATE": ["nel 1300", "nell'anno del Signore 1492", "il decimo giorno", "alle calende greche", "nel secolo XV"],
    "EVENT": ["Battaglia di Lepanto", "Sacco di Roma", "Concilio di Trento", "Guerra dei Cent'Anni", "Peste Nera"],
    "TIT": ["Duca", "Conte", "Re", "Papa", "Imperatore", "Cardinale", "Vescovo", "Marchese"],
    "REL": ["Dio", "Cristo", "Vergine Maria", "San Pietro", "Satana", "Spirito Santo"],
    "FANT": ["Cerbero", "Caronte", "Minotauro", "Gorgone", "Centauro", "Lucifero", "Idra", "Pegaso"]
}

SYSTEM_PROMPT = """Sei un esperto linguista italiano. Il tuo compito è annotare le entità (NER) in frasi storiche italiane.
Devi avvolgere le entità nel testo usando tag XML. Le categorie consentite sono:
PER (Persone), LOC (Luoghi), ORG (Organizzazioni), WORK (Opere), DATE (Date/Periodi), EVENT (Eventi storici), TIT (Titoli nobiliari/religiosi), REL (Figure religiose/divinità), FANT (Creature mitologiche/fantasy).

Esempio di input: "Dante camminava con Virgilio verso l'Inferno nel 1300."
Esempio di output: "<PER>Dante</PER> camminava con <PER>Virgilio</PER> verso l'<LOC>Inferno</LOC> <DATE>nel 1300</DATE>."

REGOLE:
- Restituisci SOLO la frase con i tag inseriti. Nessuna introduzione, nessuna spiegazione.
- Non modificare MAI il testo originale, aggiungi solo i tag XML.
- Tieni la punteggiatura FUORI dal tag se non fa parte dell'entità (es. <PER>Dante</PER>, non <PER>Dante,</PER>).
"""

def get_training_books():
    """Recupera i libri per Train e Val."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT clean_file_path FROM books WHERE used_for_dataset = 1 AND clean_file_path IS NOT NULL")
    paths = [row[0] for row in cursor.fetchall()]
    conn.close()
    return paths

def get_test_books():
    """Recupera i libri per il Test Gold Out-Of-Domain."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT clean_file_path FROM books WHERE used_for_dataset = 0 AND clean_file_path IS NOT NULL")
    paths = [row[0] for row in cursor.fetchall()]
    conn.close()
    return paths

def load_and_sample_uniformly(paths, target_total):
    """Estrae paragrafi distribuendoli in modo uniforme tra tutti i libri (Round-Robin)."""
    # Struttura: dizionario {path: [lista di paragrafi]}
    book_paragraphs = {}
    for path in paths:
        if not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                text = data.get("contenuto", data.get("text", ""))
                chunks = [p.strip() for p in text.split('\n\n') if len(p.strip()) > 50 and len(p.strip()) < 500]
                if chunks:
                    random.shuffle(chunks) # Mischiamo i paragrafi del singolo libro
                    book_paragraphs[path] = chunks
        except Exception as e:
            print(f"Errore lettura {path}: {e}")
            
    # Round-Robin per garantire uniformità assoluta
    sampled = []
    active_paths = list(book_paragraphs.keys())
    
    while len(sampled) < target_total and active_paths:
        for path in list(active_paths):
            if len(sampled) >= target_total:
                break
            if book_paragraphs[path]:
                sampled.append(book_paragraphs[path].pop(0))
            else:
                active_paths.remove(path) # Libro esaurito
                
    random.shuffle(sampled) # Mischia l'ordine finale
    return sampled

def annotate_with_claude(text, idx):
    """Chiama Claude per inserire i tag XML."""
    body = json.dumps({
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "temperature": 0.0,
        "messages": [{"role": "user", "content": text}],
    })
    
    for attempt in range(5):
        try:
            response = bedrock.invoke_model(
                modelId=MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=body,
            )
            result = json.loads(response["body"].read())
            annotated = result["content"][0]["text"].strip()
            return annotated
        except Exception as e:
            print(f"[{idx}] Errore Bedrock (tentativo {attempt+1}): {e}")
            time.sleep(2 ** attempt)
            
    print(f"[{idx}] Fallita annotazione per: {text[:30]}...")
    return None

def augment_xml(annotated_text):
    """Data Augmentation: scambia le entità nei tag XML con varianti casuali."""
    augmented = annotated_text
    
    matches = re.finditer(r'<([A-Z]+)>(.*?)</\1>', annotated_text)
    for match in matches:
        tag = match.group(1)
        original_text = match.group(2)
        
        if tag in AUGMENT_DICT:
            replacement = random.choice(AUGMENT_DICT[tag])
            old_block = f"<{tag}>{original_text}</{tag}>"
            new_block = f"<{tag}>{replacement}</{tag}>"
            augmented = augmented.replace(old_block, new_block, 1)
            
    return augmented

def tokenize_xml_to_bio(annotated_text):
    """Converte una stringa con tag XML nel formato (tokens, ner_tags) B-I-O."""
    parts = re.split(r'(<[A-Z]+>.*?</[A-Z]+>)', annotated_text)
    
    tokens = []
    ner_tags = []
    
    for part in parts:
        if not part: continue
        
        match = re.match(r'<([A-Z]+)>(.*?)</\1>', part)
        if match:
            tag_name = match.group(1)
            content = match.group(2)
            words = re.findall(r"[\w']+|[.,!?;:]", content)
            for i, w in enumerate(words):
                tokens.append(w)
                if i == 0:
                    ner_tags.append(f"B-{tag_name}")
                else:
                    ner_tags.append(f"I-{tag_name}")
        else:
            words = re.findall(r"[\w']+|[.,!?;:]", part)
            for w in words:
                tokens.append(w)
                ner_tags.append("O")
                
    return {"tokens": tokens, "ner_tags": ner_tags}

def process_chunk(info):
    idx, text, is_train = info
    annotated = annotate_with_claude(text, idx)
    if not annotated:
        return None
        
    results = []
    bio_orig = tokenize_xml_to_bio(annotated)
    results.append(bio_orig)
    
    if is_train:
        for _ in range(2):
            aug_xml = augment_xml(annotated)
            if aug_xml != annotated:
                bio_aug = tokenize_xml_to_bio(aug_xml)
                results.append(bio_aug)
                
    return results

def main():
    print("1. Caricamento e campionamento uniforme...")
    train_paths = get_training_books()
    test_paths = get_test_books()
    
    print(f"Trovati {len(train_paths)} libri per Train/Val e {len(test_paths)} per Test Gold.")
    
    # Numeri target per il Toy Dataset (Totale 200)
    TARGET_TRAIN_VAL = 180  # 160 train + 20 val
    TARGET_TEST = 20
    
    random.seed(42)
    # Estraiamo in modo perfettamente bilanciato tra i libri
    train_val_paragraphs = load_and_sample_uniformly(train_paths, TARGET_TRAIN_VAL)
    test_texts = load_and_sample_uniformly(test_paths, TARGET_TEST)
    
    train_texts = train_val_paragraphs[:160]
    val_texts = train_val_paragraphs[160:180]
    
    print(f"Split reale: {len(train_texts)} Train | {len(val_texts)} Val | {len(test_texts)} Test")
    
    # Prep per esecuzione parallela
    tasks = []
    for i, t in enumerate(train_texts): tasks.append((f"train_{i}", t, True))
    for i, t in enumerate(val_texts): tasks.append((f"val_{i}", t, False))
    for i, t in enumerate(test_texts): tasks.append((f"test_{i}", t, False))
    
    print(f"2. Annotazione con Claude 3.5 Sonnet ({len(tasks)} chiamate)...")
    train_ds, val_ds, test_ds = [], [], []
    
    completed = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        for info, result in zip(tasks, executor.map(process_chunk, tasks)):
            completed += 1
            if completed % 10 == 0:
                print(f"Completati {completed}/{len(tasks)} paragrafi...")
                
            if not result: continue
            
            group = info[0].split("_")[0]
            if group == "train":
                train_ds.extend(result) # Aggiunge originale + le varianti aumentate
            elif group == "val":
                val_ds.extend(result)
            elif group == "test":
                test_ds.extend(result)
                
    print(f"3. Salvataggio dataset...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    def save_jsonl(data, filename):
        path = os.path.join(OUTPUT_DIR, filename)
        with open(path, "w", encoding="utf-8") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        print(f"Salvato {filename} ({len(data)} righe)")
        
    save_jsonl(train_ds, "train.jsonl")
    save_jsonl(val_ds, "val.jsonl")
    save_jsonl(test_ds, "test_gold.jsonl")
    
    print("Dataset generato con successo! 🎉")

if __name__ == "__main__":
    main()
