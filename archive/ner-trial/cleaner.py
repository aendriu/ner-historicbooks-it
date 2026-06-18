import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
device = "cuda" if torch.cuda.is_available() else "cpu"
MODEL_NAME = "DeepMount00/OCR_corrector"

model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME).eval()
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
model.to(device)
my_text = "In un'epca lontnaa, un re goernava le sue tere con saggez2a e giustiia. Sotot il suo regno, il rgeno prosperava e la getne era flice. Ma un gionro, un drgoa feroce attcò il regno, semniando ditruzione e paurra tra i suoi abtanti."
inputs = tokenizer(my_text, return_tensors="pt").to(device)
outputs = model.generate(input_ids=inputs['input_ids'],
               attention_mask=inputs['attention_mask'],
               num_beams=2, max_length=1050, top_k=10)
clean_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
print(clean_text)
