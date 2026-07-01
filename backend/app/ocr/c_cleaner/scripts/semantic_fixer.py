#!/usr/bin/env python3
import os
import json
import re
import sys

def semantic_clean(text):
    if not text:
        return text

    # 1. Isolated Uppercase Consonants (e.g., "G iovanni" -> "Giovanni")
    # Matches a word boundary, an uppercase consonant, a space, and a lowercase Italian word.
    text = re.sub(r'\b([B-DF-HJ-NP-TV-Z]) ([a-zàèéìòù]+)\b', r'\1\2', text)
    
    # 2. Specific Drop-Cap Vowels Whitelist
    text = re.sub(r'\bO nde\b', 'Onde', text)
    text = re.sub(r'\bI nghilterra\b', 'Inghilterra', text)
    text = re.sub(r'\bI Spagna\b', 'In Spagna', text)
    text = re.sub(r'\bI o\b', 'Io', text)
    text = re.sub(r'\bU rbino\b', 'Urbino', text)
    text = re.sub(r'\bM essina\b', 'Messina', text) # M is handled by rule 1, but just in case
    
    # 3. Fused Words / CamelCase (e.g., "AndreaTaffi" -> "Andrea Taffi")
    text = re.sub(r'([a-zàèéìòù])([A-Z])', r'\1 \2', text)
    
    # 4. Cap and Roman Numerals (e.g., "CapXII" -> "Cap XII")
    text = re.sub(r'\bCap([IVXLCDM]+)\b', r'Cap \1', text)
    
    # 5. Dictionary of specific OCR Typos and deformities
    dictionary_replacements = {
        "peri tipi": "per i tipi",
        "ma gnanimità": "magnanimità",
        "incli nazione": "inclinazione",
        "col pa": "colpa",
        "Beliosi": "Bellosi",
        "Fra’ iovanni": "Fra' Giovanni",
        "Fra' iovanni": "Fra' Giovanni",
        "Antonio EePiero Poliamoli": "Antonio e Piero Pollaiolo",
        "G uglielmo da M ardila": "Guglielmo da Marcillat",
        "M arco Caiavrese": "Marco Calavrese",
        "iulio Ili": "Giulio III",
        "PTassitele": "Prassitele",
        "Cap. Ili": "Cap. III",
        "Cap. IMI": "Cap. VIII",
        "Cap. X II II": "Cap. XIV",
        "Cap. XVII II": "Cap. XVIII",
        "Cap. XXVII1110I": "Cap. XXVII",
        "Cap 93": "Cap. XCIII",
        "Cap 104": "Cap. CIV",
        "Cap 117": "Cap. CXVII",
        "ALLO ILLUSTRI S 1 O E ECCELLENTISSIMOSIGNORE": "ALLO ILLUSTRISSIMO E ECCELLENTISSIMO SIGNORE",
    }
    
    for typo, correction in dictionary_replacements.items():
        text = text.replace(typo, correction)
        
    return text

def main():
    if len(sys.argv) != 2:
        print("Usage: python3 semantic_fixer.py <directory>")
        sys.exit(1)
        
    directory = sys.argv[1]
    
    if not os.path.isdir(directory):
        print(f"Directory non valida: {directory}")
        sys.exit(1)
        
    print(f"Applicando fix semantici sulla directory: {directory}...")
    
    for filename in os.listdir(directory):
        if not filename.endswith(".json"):
            continue
            
        file_path = os.path.join(directory, filename)
        
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                print(f"Skipping invalid JSON: {filename}")
                continue
                
        if "contenuto" in data and isinstance(data["contenuto"], str):
            original = data["contenuto"]
            cleaned = semantic_clean(original)
            
            if original != cleaned:
                data["contenuto"] = cleaned
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)

    print("Fix semantici applicati con successo.")

if __name__ == "__main__":
    main()
