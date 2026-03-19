import sys
sys.path.insert(0, '.')
from src.pdf_to_image import convert_pdf_to_images
from src.ocr_engine import run_ocr

images = convert_pdf_to_images('data/Built_Right_Sample_CQ.pdf', dpi=300)

print("=== PAGE 1 — Fields of interest ===")
tokens = run_ocr(images[0], page=0)

keywords = ["company", "phone", "email", "address", "@", "contact", "primary"]
for t in tokens:
    tl = t["text"].lower()
    if any(k in tl for k in keywords):
        print(f"  cy={t['cy']:4}  cx={t['cx']:4}  x={t['x']:4}  x2={t['x2']:4}  [{t['text']}]")

print()
print("=== PAGE 3 — Reference company name tokens ===")
tokens3 = run_ocr(images[2], page=2)
ref_keywords = ["cool", "civil", "mill", "empow", "spring", "abc", "mechanical",
                "dirtwork", "international", "electrical", "engineering", "supply"]
for t in tokens3:
    tl = t["text"].lower()
    if any(k in tl for k in ref_keywords):
        print(f"  cy={t['cy']:4}  cx={t['cx']:4}  x={t['x']:4}  x2={t['x2']:4}  [{t['text']}]")