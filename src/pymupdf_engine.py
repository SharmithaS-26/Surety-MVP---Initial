"""
pymupdf_engine.py
Extracts text from a digital PDF using PyMuPDF — zero OCR noise.

This PDF has TWO text layers (display + form field layer), causing each
word to appear twice at slightly different coordinates. We deduplicate
at the RAW WORD level before any grouping, using a tight spatial match.

Token format identical to ocr_engine.py output.
Coordinates scaled from PDF points (72 dpi) to 300 DPI pixels.
"""

import fitz

DPI   = 300
SCALE = DPI / 72.0   # 4.1667x

# Words within this many PDF points of each other (same text) = duplicate
DEDUP_PT = 6.0


def extract_tokens(pdf_path: str, page_num: int = 0) -> list[dict]:
    doc   = fitz.open(pdf_path)
    page  = doc[page_num]
    words = page.get_text("words")   # (x0,y0,x1,y1,text,block,line,word)
    doc.close()

    if not words:
        return []

    # ── Step 1: Deduplicate raw words BEFORE grouping ─────────────────────────
    # This PDF has two text layers; each word appears twice at ~same position.
    # Keep only the first occurrence of any word within DEDUP_PT points.
    sorted_w = sorted(words, key=lambda w: (w[1], w[0]))  # top-left first
    deduped_words = []
    for w in sorted_w:
        is_dup = any(
            p[4] == w[4]                      # identical text
            and abs(p[1] - w[1]) <= DEDUP_PT  # same y
            and abs(p[0] - w[0]) <= DEDUP_PT  # same x
            for p in deduped_words
        )
        if not is_dup:
            deduped_words.append(w)

    removed = len(words) - len(deduped_words)

    # ── Step 2: Sort top→bottom, left→right ───────────────────────────────────
    deduped_words.sort(key=lambda w: (round(w[1] / 2) * 2, w[0]))

    # ── Step 3: Group into lines (words with similar y0) ─────────────────────
    LINE_GAP = 3.0
    lines = []
    if deduped_words:
        current = [deduped_words[0]]
        for w in deduped_words[1:]:
            if abs(w[1] - current[-1][1]) <= LINE_GAP:
                current.append(w)
            else:
                lines.append(sorted(current, key=lambda w: w[0]))
                current = [w]
        lines.append(sorted(current, key=lambda w: w[0]))

    # ── Step 4: Group words into tokens by horizontal proximity ───────────────
    # Words with gap <= 15pt are joined into one token
    # Words with gap > 15pt become separate tokens (preserves label|value split)
    tokens = []
    for line in lines:
        groups, cur = [], [line[0]]
        for w in line[1:]:
            if w[0] - cur[-1][2] > 15:
                groups.append(cur)
                cur = [w]
            else:
                cur.append(w)
        groups.append(cur)

        for g in groups:
            text = " ".join(w[4] for w in g).strip()
            if not text:
                continue
            x0 = int(min(w[0] for w in g) * SCALE)
            y0 = int(min(w[1] for w in g) * SCALE)
            x1 = int(max(w[2] for w in g) * SCALE)
            y1 = int(max(w[3] for w in g) * SCALE)
            tokens.append({
                "text": text,
                "x": x0, "y": y0, "x2": x1, "y2": y1,
                "cx": (x0 + x1) // 2,
                "cy": (y0 + y1) // 2,
                "conf": 1.0,
                "page": page_num,
            })

    tokens.sort(key=lambda t: (t["y"], t["x"]))
    print(f"  [pymupdf_engine] Page {page_num + 1}: "
          f"{len(tokens)} tokens ({removed} duplicates removed).")
    return tokens


def extract_all_pages(pdf_path: str) -> list[list[dict]]:
    doc = fitz.open(pdf_path)
    n   = len(doc)
    doc.close()
    return [extract_tokens(pdf_path, i) for i in range(n)]


def is_digital_pdf(pdf_path: str, page_num: int = 0,
                   min_words: int = 20) -> bool:
    """
    Returns True if the PDF has a real text layer (digital/born-digital).
    Returns False if it appears to be a scanned image.
    """
    doc   = fitz.open(pdf_path)
    page  = doc[page_num]
    words = page.get_text("words")
    doc.close()
    result = len(words) >= min_words
    print(f"  [pdf_detector] {len(words)} words on page 1 "
          f"→ {'digital PDF (PyMuPDF mode)' if result else 'scanned PDF (OCR mode)'}")
    return result