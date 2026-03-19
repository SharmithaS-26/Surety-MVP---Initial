import sys
sys.path.insert(0, '.')
import numpy as np
from PIL import Image
from src.pdf_to_image import convert_pdf_to_images
from src.ocr_engine import run_ocr

LOOK_LEFT_PX  = 120
STRIP_H_PX    = 55
DARK_THRESHOLD = 100

def inspect(image, label_x, label_cy):
    x1 = max(0, label_x - LOOK_LEFT_PX)
    x2 = max(x1 + 20, label_x - 4)
    y1 = max(0, label_cy - STRIP_H_PX // 2)
    y2 = min(image.height, label_cy + STRIP_H_PX // 2)
    region = image.crop((x1, y1, x2, y2))
    arr = np.array(region.convert("L"))
    ratio = float(np.sum(arr < DARK_THRESHOLD)) / arr.size
    return ratio

ANCHOR_LABELS = {
    "yes", "no", "llc", "llp", "\"c\" corp", "\"s\" corp",
    "proprietorship", "joint venture", "8a", "hubzone", "wob",
    "vob", "sdvosb", "other", "non-union", "union", "cash",
    "completed job", "accrual", "% of completion", "% of comp",
    "cpa audit", "cpa review", "compilation",
}

images = convert_pdf_to_images('data/Built_Right_Sample_CQ.pdf', dpi=300)

for page_num in [0, 1]:
    img = images[page_num]
    tokens = run_ocr(img, page=page_num)
    print(f"\n=== PAGE {page_num + 1} ANCHOR RATIOS ===")
    print(f"  {'label':<20} {'cy':>5}  {'ratio':>8}")
    print(f"  {'-'*20} {'-'*5}  {'-'*8}")
    for tok in tokens:
        if tok["text"].strip().lower() in ANCHOR_LABELS:
            ratio = inspect(img, tok["x"], tok["cy"])
            print(f"  {tok['text']:<20} {tok['cy']:>5}  {ratio:>8.4f}")