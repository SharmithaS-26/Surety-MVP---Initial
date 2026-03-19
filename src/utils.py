"""
utils.py
Shared spatial helpers, text-cleaning utilities, and Yes/No resolution logic
used by all page parsers.
"""

import re
import json
import os
from typing import Optional


# ── Text cleaning ─────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Strip whitespace and lone punctuation OCR artefacts."""
    text = text.strip()
    text = re.sub(r'^[|:*\-–—]+$', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


# ── Spatial token helpers ─────────────────────────────────────────────────────

def tokens_in_region(tokens: list[dict],
                      x1: int, y1: int,
                      x2: int, y2: int) -> list[dict]:
    """Return tokens whose center (cx, cy) falls within the rectangle."""
    return [t for t in tokens
            if x1 <= t["cx"] <= x2 and y1 <= t["cy"] <= y2]


def tokens_on_row(tokens: list[dict], cy: int,
                   tolerance: int = 12) -> list[dict]:
    """Return tokens within `tolerance` px of vertical center `cy`, sorted left→right."""
    return sorted(
        [t for t in tokens if abs(t["cy"] - cy) <= tolerance],
        key=lambda t: t["x"]
    )


def join_row_tokens(tokens: list[dict]) -> str:
    """Concatenate token texts with spaces."""
    return " ".join(t["text"] for t in tokens).strip()


# ── Adaptive row clustering ───────────────────────────────────────────────────

def cluster_rows(tokens: list[dict], gap: int = 14) -> list[list[dict]]:
    """
    Group tokens into rows by vertical proximity.
    Tokens whose cy values differ by <= gap px are in the same row.
    Returns a list of rows (each row = list of tokens sorted left→right),
    sorted top→bottom.
    """
    if not tokens:
        return []
    sorted_toks = sorted(tokens, key=lambda t: t["cy"])
    rows, cur = [], [sorted_toks[0]]
    for tok in sorted_toks[1:]:
        if tok["cy"] - cur[-1]["cy"] <= gap:
            cur.append(tok)
        else:
            rows.append(sorted(cur, key=lambda t: t["x"]))
            cur = [tok]
    rows.append(sorted(cur, key=lambda t: t["x"]))
    return rows


def row_cy(row: list[dict]) -> int:
    """Vertical center of a clustered row."""
    return int(sum(t["cy"] for t in row) / len(row)) if row else 0


def row_text(row: list[dict]) -> str:
    return join_row_tokens(row)


def find_row(rows: list[list[dict]], *keywords, skip: int = 0) -> list[dict]:
    """
    Return the first row whose text contains ALL given keywords (case-insensitive).
    skip: skip the first N matching rows (useful when a keyword appears twice).
    Returns [] if not found.
    """
    found = 0
    for row in rows:
        rt = row_text(row).lower()
        if all(kw.lower() in rt for kw in keywords):
            if found >= skip:
                return row
            found += 1
    return []


def after_kw(row: list[dict], keyword: str) -> str:
    """Return joined text of tokens after the one containing `keyword`."""
    for i, t in enumerate(row):
        if keyword.lower() in t["text"].lower():
            return join_row_tokens(row[i + 1:])
    return join_row_tokens(row)


def between_kw(row: list[dict], start_kw: str,
                end_kw: Optional[str] = None,
                pw: int = 720) -> str:
    """Return joined text of tokens between start_kw and end_kw tokens."""
    start_x, end_x = 0, pw
    for t in row:
        if start_kw.lower() in t["text"].lower():
            start_x = t["x2"]
        if end_kw and end_kw.lower() in t["text"].lower():
            end_x = t["x"]
    return join_row_tokens(
        [t for t in row if t["x"] >= start_x and t["x2"] <= end_x]
    )


def toks_in_x_band(row: list[dict],
                    frac_start: float, frac_end: float,
                    pw: int) -> list[dict]:
    """Return tokens whose x position falls within a fractional x-band of the page."""
    x1, x2 = int(frac_start * pw), int(frac_end * pw)
    return [t for t in row if t["x"] >= x1 and t["x2"] <= x2 + 20]


# ── Checkbox spatial helpers ──────────────────────────────────────────────────

def checkboxes_in_region(boxes: list[dict],
                          x1: int, y1: int,
                          x2: int, y2: int) -> list[dict]:
    """Return checkboxes whose center falls within the rectangle."""
    return [b for b in boxes
            if x1 <= b["cx"] <= x2 and y1 <= b["cy"] <= y2]


def checkbox_on_row(boxes: list[dict], cy: int,
                     tolerance: int = 22) -> list[dict]:
    """Return checkboxes within tolerance px of vertical center cy, sorted left to right."""
    return sorted(
        [b for b in boxes if abs(b["cy"] - cy) <= tolerance],
        key=lambda b: b["cx"]
    )


# ── Yes/No resolution ─────────────────────────────────────────────────────────
#
# checkbox_detector inspects pixel regions left of every Yes/No token and
# emits a box entry for EACH with checked=True/False and a label field.

def resolve_yn_from_checkboxes(boxes_on_row: list[dict],
                                row_tokens: Optional[list[dict]] = None) -> Optional[str]:
    """
    Given checkbox boxes on a Yes|No row, return "Yes", "No", or None.
    Each box has a label field ("Yes" or "No") and a checked bool.
    """
    if not boxes_on_row:
        return None

    yn_words = {"yes", "no"}

    # Strategy 1: use the label field directly
    for box in boxes_on_row:
        label = box.get("label", "").strip().lower()
        if label in yn_words and box.get("checked"):
            return box["label"].strip().capitalize()

    # Strategy 2: positional fallback
    checked = [b for b in boxes_on_row if b.get("checked")]
    if not checked:
        return None
    all_sorted = sorted(boxes_on_row, key=lambda b: b["cx"])
    if len(all_sorted) >= 2:
        leftmost_cx  = all_sorted[0]["cx"]
        rightmost_cx = all_sorted[-1]["cx"]
        leftmost_checked  = min(checked, key=lambda b: b["cx"])
        rightmost_checked = max(checked, key=lambda b: b["cx"])
        if leftmost_checked["cx"] <= leftmost_cx + 20:
            return "Yes"
        if rightmost_checked["cx"] >= rightmost_cx - 20:
            return "No"
    return "Yes" if checked else None


def checked_labels(row: list[dict], boxes: list[dict],
                    max_dx: int = 180, dy: int = 22) -> list[str]:
    """
    Return label text for all CHECKED boxes on this row that are NOT Yes/No.
    Uses the label field from checkbox_detector output.
    """
    if not row:
        return []
    cy = row_cy(row)
    row_boxes = checkbox_on_row(boxes, cy, tolerance=dy)
    yn_words = {"yes", "no"}
    labels = []
    for box in row_boxes:
        if not box.get("checked"):
            continue
        label = box.get("label", "").strip()
        if label.lower() not in yn_words and label:
            labels.append(label)
    return labels


def yn_from_row(row: list[dict], boxes: list[dict],
                dy: int = 22) -> Optional[str]:
    """Resolve Yes/No for a given row using the label-aware checkbox format."""
    if not row:
        return None
    row_boxes_list = checkbox_on_row(boxes, row_cy(row), tolerance=dy)
    return resolve_yn_from_checkboxes(row_boxes_list)


# ── Page geometry ─────────────────────────────────────────────────────────────

def page_width(tokens: list[dict]) -> int:
    return max((t["x2"] for t in tokens), default=720)


def page_height(tokens: list[dict]) -> int:
    return max((t["y2"] for t in tokens), default=1200)


# ── JSON output ───────────────────────────────────────────────────────────────

def save_json(data: dict, output_path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  [utils] JSON saved → {output_path}")