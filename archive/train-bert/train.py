import os
import json
import torch
import numpy as np
from datasets import Dataset
from transformers import (
    AutoTokenizer, 
    AutoModelForTokenClassification, 
    TrainingArguments, 
    Trainer,
    DataCollatorForTokenClassification
)
from torch import nn
from collections import Counter

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# --- 1. CONFIGURAZIONE ---
MODEL_NAME = "dbmdz/bert-base-italian-xxl-cased"
TRAIN_FILE = "train.jsonl"
EVAL_FILE = "gold.jsonl"
OUTPUT_DIR = "./modello_ner_italiano"

# Mappatura etichette
label_list = ["O", "B-FANT", "I-FANT", "B-REL", "I-REL", "B-PER", "I-PER", 
              "B-LOC", "I-LOC", "B-ORG", "I-ORG", "B-WORK", "I-WORK", 
              "B-DATE", "I-DATE", "B-EVENT", "I-EVENT", "B-TIT", "I-TIT"]
label2id = {l: i for i, l in enumerate(label_list)}
id2label = {i: l for i, l in enumerate(label_list)}

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

# --- 1b. CALCOLO CLASS WEIGHTS ---
def calculate_class_weights(train_dataset, label2id):
    """Calcola class weights dall'inverse frequency"""
    label_counts = Counter()
    total_tokens = 0
    
    for example in train_dataset:
        labels = example.get("labels", [])
        for lbl in labels:
            if lbl != -100:  # Esclude token speciali
                label_counts[lbl] += 1
                total_tokens += 1
    
    # Inverse frequency weights
    num_classes = len(label2id)
    class_weights = torch.ones(num_classes, dtype=torch.float32)
    
    for label_id in range(num_classes):
        count = label_counts.get(label_id, 1)
        class_weights[label_id] = total_tokens / (num_classes * (count + 1))
    
    # Normalizza rispetto al peso minimo (per evitare numeri troppo grandi)
    min_weight = class_weights.min()
    class_weights = class_weights / min_weight
    
    print(f"📊 Class weights calcolati:")
    for label_id, weight in enumerate(class_weights.tolist()):
        label_name = {v: k for k, v in label2id.items()}[label_id]
        print(f"  {label_name:<10} → {weight:.2f}")
    
    # Clamp weights to avoid excessive amplification on extremely rare labels.
    max_weight_env = os.environ.get("MAX_CLASS_WEIGHT")
    try:
        max_weight = float(max_weight_env) if max_weight_env is not None else 10.0
    except Exception:
        max_weight = 10.0

    class_weights = torch.clamp(class_weights, max=max_weight)
    print(f"📌 Class weights clamped to max={max_weight}")
    return class_weights

# --- 2. FUNZIONE DI CONVERSIONE (Offset -> BIO Tags) ---
def convert_to_bio(example):
    text = example["sentence"]
    entities = example["entities"]
    
    # Tokenizziamo mantenendo traccia degli offset
    tokenized = tokenizer(text, truncation=True, return_offsets_mapping=True)
    offsets = tokenized["offset_mapping"]

    # Token speciali ignorati (-100), token testuali fuori entity marcati come O.
    labels = [label2id["O"] if o_start != o_end else -100 for o_start, o_end in offsets]

    for ent in entities:
        start, end, label = ent["start_char"], ent["end_char"], ent["label"]
        start_tag = f"B-{label}"
        inside_tag = f"I-{label}"

        if start_tag not in label2id or inside_tag not in label2id:
            continue
        
        first_token = True
        for i, (o_start, o_end) in enumerate(offsets):
            # Saltiamo i token speciali ([CLS], [SEP])
            if o_start == o_end:
                continue
            
            # Label su qualsiasi token con overlap con l'intervallo entity.
            if o_start < end and o_end > start:
                if first_token:
                    labels[i] = label2id[start_tag]
                    first_token = False
                else:
                    labels[i] = label2id[inside_tag]

    tokenized.pop("offset_mapping")
    tokenized["labels"] = labels
    return tokenized

# --- 3b. CUSTOM TRAINER CON CLASS WEIGHTS ---
class WeightedTrainer(Trainer):
    def __init__(self, *args, class_weights=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.class_weights = class_weights
    
    def compute_loss(self, model, inputs, return_outputs=False):
        labels = inputs.pop("labels")
        outputs = model(**inputs)
        logits = outputs.logits
        
        # Reshape per CrossEntropyLoss: [batch_size * seq_len, num_labels]
        loss_fct = nn.CrossEntropyLoss(weight=self.class_weights, reduction='mean')
        active_loss = inputs["attention_mask"].view(-1) == 1
        active_logits = logits.view(-1, self.model.config.num_labels)[active_loss]
        active_labels = labels.view(-1)[active_loss]
        
        loss = loss_fct(active_logits, active_labels)
        
        return (loss, outputs) if return_outputs else loss

# --- 3. CARICAMENTO DATI ---
def load_jsonl(path):
    data = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            data.append(json.loads(line))
    return Dataset.from_list(data)

print("📖 Caricamento dataset...")
print("↳ preparo train")
train_raw = load_jsonl(TRAIN_FILE)
train_ds = train_raw.map(
    convert_to_bio,
    remove_columns=train_raw.column_names,
    desc="Preparazione train",
)
print("↳ preparo eval")
eval_raw = load_jsonl(EVAL_FILE)
eval_ds = eval_raw.map(
    convert_to_bio,
    remove_columns=eval_raw.column_names,
    desc="Preparazione eval",
)

# Calcola class weights
print("↳ calcolo class weights")
class_weights = calculate_class_weights(train_ds, label2id)
if torch.cuda.is_available():
    class_weights = class_weights.cuda()

# --- 4. MODELLO E TRAINING ---
model = AutoModelForTokenClassification.from_pretrained(
    MODEL_NAME, 
    num_labels=len(label_list),
    id2label=id2label,
    label2id=label2id
)

training_args = TrainingArguments(
    output_dir=OUTPUT_DIR,
    eval_strategy="epoch",
    save_strategy="epoch",
    learning_rate=2e-5,
    per_device_train_batch_size=8, # Alza a 16 se hai una buona GPU
    per_device_eval_batch_size=8,
    num_train_epochs=4,            # 4 epoche sono lo "sweet spot"
    weight_decay=0.01,
    load_best_model_at_end=True,
    logging_steps=100,
    logging_first_step=True,
    disable_tqdm=False,
    push_to_hub=False,
    fp16=torch.cuda.is_available() # Accelera se hai una GPU NVIDIA
)

trainer = WeightedTrainer(
    model=model,
    args=training_args,
    train_dataset=train_ds,
    eval_dataset=eval_ds,
    data_collator=DataCollatorForTokenClassification(tokenizer),
    class_weights=class_weights,
)

print("Partenza addestramento!")
trainer.train()

# Salva il modello finale
trainer.save_model(OUTPUT_DIR)
tokenizer.save_pretrained(OUTPUT_DIR)
print(f"✅ Modello salvato in {OUTPUT_DIR}")