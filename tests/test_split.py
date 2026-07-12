import re, json
def split_into_paragraphs(text):
    TARGET_SIZE = 500
    result = []
    sentences = re.split(r'(?<=[.!?])[\s\n]+', text)
    current_para_text = ""
    current_start = 0
    for s in sentences:
        s = s.strip()
        if not s: continue
        if current_para_text:
            current_para_text += " " + s
        else:
            current_para_text = s
        if len(current_para_text) >= TARGET_SIZE:
            start_idx = text.find(current_para_text[:50], current_start)
            if start_idx == -1: start_idx = current_start
            end_idx = start_idx + len(current_para_text)
            result.append({"text": current_para_text, "char_start": start_idx, "char_end": end_idx})
            current_start = end_idx
            current_para_text = ""
    if current_para_text:
        start_idx = text.find(current_para_text[:50], current_start)
        if start_idx == -1: start_idx = current_start
        end_idx = start_idx + len(current_para_text)
        result.append({"text": current_para_text, "char_start": start_idx, "char_end": end_idx})
    return result

with open('/home/aendriu/Para/Project/ocr/ocr-rb/ocr-rb-cleaner/data/metadata_cleaned/002_Bandello_Le_novelle_1_si286-cleaned.json') as f:
    text = json.load(f)['contenuto'][:5000]

paras = split_into_paragraphs(text)
for i, p in enumerate(paras[:5]):
    print(f"Para {i}: size={len(p['text'])}, text={repr(p['text'][:50])}...")
