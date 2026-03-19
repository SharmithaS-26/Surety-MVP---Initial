import sys
sys.path.insert(0, '.')
import fitz

doc = fitz.open('data/Built_Right_Sample_CQ.pdf')

for page_num in range(min(2, len(doc))):
    page = doc[page_num]
    print(f"\n=== PAGE {page_num + 1} ===")
    blocks = page.get_text("dict")["blocks"]
    for b in blocks:
        if b["type"] != 0:
            continue
        for line in b["lines"]:
            for span in line["spans"]:
                text = span["text"].strip()
                if text:
                    x0, y0, x1, y1 = span["bbox"]
                    print(f"  y={int(y0):4}  x={int(x0):4}  [{text}]")