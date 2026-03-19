"""
ocr_engine.py
Runs EasyOCR on a PIL Image and returns word-level tokens with
bounding box coordinates and confidence scores.

Token format:
    {
        "text":  str,
        "x":     int,   # left edge (pixels)
        "y":     int,   # top edge
        "x2":    int,   # right edge
        "y2":    int,   # bottom edge
        "cx":    int,   # horizontal center
        "cy":    int,   # vertical center
        "conf":  float, # EasyOCR confidence 0-1
        "page":  int    # 0-based page index
    }
"""

import easyocr
import numpy as np
from PIL import Image

_reader = None


def get_reader() -> easyocr.Reader:
    global _reader
    if _reader is None:
        print("  [ocr_engine] Loading EasyOCR model (first run only)…")
        _reader = easyocr.Reader(["en"], gpu=False)
        print("  [ocr_engine] Model ready.")
    return _reader


def run_ocr(image: Image.Image, page: int = 0,
            conf_threshold: float = 0.2) -> list[dict]:
    """
    Run EasyOCR on a PIL Image and return sorted token list.

    Args:
        image:          PIL Image (RGB, 300 DPI recommended).
        page:           Page index for token labelling.
        conf_threshold: Drop tokens below this confidence.

    Returns:
        List of token dicts sorted top-to-bottom, left-to-right.
    """
    reader = get_reader()
    img_np = np.array(image)
    raw    = reader.readtext(img_np, detail=1, paragraph=False)

    tokens = []
    for (bbox, text, conf) in raw:
        if conf < conf_threshold or not text.strip():
            continue
        xs = [pt[0] for pt in bbox]
        ys = [pt[1] for pt in bbox]
        x1, y1 = int(min(xs)), int(min(ys))
        x2, y2 = int(max(xs)), int(max(ys))
        tokens.append({
            "text": text.strip(),
            "x":    x1, "y":  y1,
            "x2":   x2, "y2": y2,
            "cx":   (x1 + x2) // 2,
            "cy":   (y1 + y2) // 2,
            "conf": round(conf, 3),
            "page": page,
        })

    tokens.sort(key=lambda t: (t["y"], t["x"]))
    print(f"  [ocr_engine] Page {page + 1}: {len(tokens)} tokens.")
    return tokens