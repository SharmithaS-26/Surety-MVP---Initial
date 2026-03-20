"""
checkbox_detector.py
Detects checked checkboxes by inspecting small pixel regions to the LEFT
of every Yes/No label token that EasyOCR found on the page.

WHY THIS APPROACH:
  The Built Right CQ PDF renders tick marks (✓) and filled squares (■) as
  vector graphics, not unicode text. EasyOCR ignores vector graphics entirely
  and only returns text tokens — so tick symbols never appear in the token list.

  However, EasyOCR DOES correctly find every "Yes" and "No" label token with
  accurate bounding boxes. The checkbox always sits immediately to the LEFT of
  its label. So we:
    1. Find all "Yes" and "No" tokens on the page
    2. Crop a small region just to the LEFT of each token
    3. Check if that region contains a dark mark (tick or filled square)
    4. If yes → that option is checked

SPECIAL CASES handled:
  - Business type row: checkboxes left of LLC, "C" Corp, LLP, etc.
  - Special Designations row: checkboxes left of 8A, HUBZone, WOB, etc.
  - Union / Non-Union: filled square left of the label
  - Tax/Fin basis rows: checkboxes left of Cash, Completed Job, Accrual, etc.

Output per detected checkbox:
    {
        "x", "y", "x2", "y2": region inspected (int)
        "cx", "cy":            center of the label token (int)
        "checked":             bool
        "style":               "tick" | "filled" | "empty"
        "label":               str  — the label text (Yes / No / LLC / etc.)
        "page":                int  (0-based)
    }
"""

import numpy as np
from PIL import Image

# ── Tunable constants ─────────────────────────────────────────────────────────

# How far LEFT of the label token to look for a checkbox mark (px at 300 DPI)
LOOK_LEFT_PX  = 100

# Height of the inspection strip (centred on the label token cy)
STRIP_H_PX    = 55

# Minimum width of the search region
MIN_REGION_W  = 20

# Dark pixel threshold — pixels below this value count as "dark"
DARK_THRESHOLD = 100

# If more than this fraction of the region is dark → checked
CHECKED_RATIO  = 0.155  # calibrated: gap between 0.1521 (empty) and 0.1855 (checked)

# Lower threshold for PDF form-field style checkboxes (☐/☑)
# These are small checkbox squares producing much lower pixel density than large ✓ marks
FORM_FIELD_RATIO = 0.03


def _is_form_field_token(text: str) -> bool:
    """Return True if token contains a PDF form-field checkbox symbol (☐ or ☑)."""
    return "☐" in text or "☑" in text


# Labels we treat as checkbox-anchors (i.e. look left of these for a mark)
YES_NO_LABELS = {"yes", "no"}

# Other checkbox-anchored labels (business type, designations, union, basis rows)
OTHER_LABELS = {
    "llc", "llp", "\"c\" corp", "\"s\" corp", "c\" corp", "s\" corp",
    "proprietorship", "joint venture",
    "8a", "hubzone", "wob", "vob", "sdvosb", "other",
    "non-union", "union",
    "cash", "completed job", "accrual", "% of completion", "% of comp",
    "cpa audit", "cpa review", "compilation",
}

ALL_ANCHOR_LABELS = YES_NO_LABELS | OTHER_LABELS


def _is_anchor(text: str) -> bool:
    t = text.strip()
    # Direct match
    if t.lower() in ALL_ANCHOR_LABELS:
        return True
    # Strip leading checkbox symbol (☐, ☑, |) and recheck
    t_clean = t.lstrip("☐☑✓| ").rstrip("| ").strip()
    if t_clean.lower() in ALL_ANCHOR_LABELS:
        return True
    # Handle "Yes |" or "No If yes..." — starts with a known label
    for label in ALL_ANCHOR_LABELS:
        if t_clean.lower().startswith(label + " ") or t_clean.lower().startswith(label + "|"):
            return True
    # Handle ☐-prefixed tokens: "☐ Non-Union", "☐ Union", etc.
    if "☐" in t or "☑" in t:
        t_no_box = t.replace("☐","").replace("☑","").strip().lstrip("| ").rstrip("| ").strip()
        if t_no_box.lower() in ALL_ANCHOR_LABELS:
            return True
    return False


def _dark_ratio(img_array: np.ndarray) -> float:
    """Fraction of pixels darker than DARK_THRESHOLD in a grayscale array."""
    if img_array.size == 0:
        return 0.0
    gray = img_array if img_array.ndim == 2 else np.mean(img_array, axis=2)
    return float(np.sum(gray < DARK_THRESHOLD)) / gray.size


def _inspect_region(image: Image.Image,
                     label_x: int, label_cy: int,
                     page_w: int,
                     threshold: float = None) -> tuple[bool, str, tuple]:
    if threshold is None:
        threshold = CHECKED_RATIO
    """
    Crop the region immediately to the LEFT of a label token and check
    whether it contains a dark mark.

    Returns: (is_checked, style, bbox_of_region)
    """
    # Region: from (label_x - LOOK_LEFT_PX) to (label_x - 4) px
    # centred vertically on label_cy ± STRIP_H_PX/2
    x1 = max(0, label_x - LOOK_LEFT_PX)
    x2 = max(x1 + MIN_REGION_W, label_x - 4)
    y1 = max(0, label_cy - STRIP_H_PX // 2)
    y2 = min(image.height, label_cy + STRIP_H_PX // 2)

    region = image.crop((x1, y1, x2, y2))
    arr    = np.array(region.convert("L"))   # grayscale
    ratio  = _dark_ratio(arr)

    if ratio >= 0.20:
        style = "filled"
    elif ratio >= CHECKED_RATIO:
        style = "tick"
    else:
        style = "empty"

    return (style != "empty"), style, (x1, y1, x2, y2)


def detect_checkboxes(image: Image.Image,
                      page: int = 0,
                      tokens: list[dict] | None = None) -> list[dict]:
    """
    Detect checked checkboxes by inspecting the pixel region left of each
    Yes/No and other checkbox-anchor token.

    Args:
        image:   PIL Image of the page at 300 DPI. REQUIRED — pixel inspection.
        page:    0-based page index.
        tokens:  EasyOCR token list from ocr_engine.run_ocr(). REQUIRED.

    Returns:
        List of checkbox dicts (both checked AND unchecked), sorted top→bottom,
        left→right. Callers use the checked=True/False flag.
    """
    if tokens is None or image is None:
        print(f"  [checkbox_detector] Page {page + 1}: "
              f"image and tokens required.")
        return []

    pw = image.width
    checkboxes = []

    for tok in tokens:
        if not _is_anchor(tok["text"]):
            continue

        # For tokens like "☐ Yes", inspect from the actual label word start
        # Strip leading checkbox symbols to find true label x position
        label_x = tok["x"]
        t_stripped = tok["text"].lstrip("☐☑✓| ")
        if len(t_stripped) < len(tok["text"].strip()):
            # Estimate x of the actual word (each char ~7pt wide at 300dpi)
            stripped_chars = len(tok["text"].strip()) - len(t_stripped)
            label_x = tok["x"] + int(stripped_chars * 28)  # ~7pt * 4.167 scale

        is_checked, style, bbox = _inspect_region(
            image, label_x, tok["cy"], pw,
            threshold=FORM_FIELD_RATIO if _is_form_field_token(tok["text"])
            else CHECKED_RATIO
        )
        x1, y1, x2, y2 = bbox

        # Store cleaned label (strip ☐/☑ prefix) for Yes/No resolution
        clean_label = tok["text"].strip().lstrip("☐☑✓| ").rstrip("| ").strip()
        # Get the actual ratio for post-processing (stored temporarily as _ratio)
        roi_arr = np.array(image.crop((x1, y1, x2, y2)).convert("L"))
        actual_ratio = _dark_ratio(roi_arr)
        checkboxes.append({
            "x":       x1,
            "y":       y1,
            "x2":      x2,
            "y2":      y2,
            "cx":      tok["cx"],
            "cy":      tok["cy"],
            "checked": is_checked,
            "style":   style,
            "label":   clean_label,
            "page":    page,
            "_ratio":  actual_ratio,  # used for pair resolution, removed after
        })

    # ── Post-process: resolve form-field Yes/No pairs by relative ratio ──────
    # For ☐/☑ style pairs (e.g. "☐ Yes" and "☐ No" on same row),
    # both may exceed FORM_FIELD_RATIO=0.03 due to border pixels.
    # The truly checked one has a HIGHER ratio — use relative comparison.
    from collections import defaultdict
    row_groups = defaultdict(list)
    for i, cb in enumerate(checkboxes):
        if cb.get("_ratio") is not None and cb.get("_ratio", 1) < CHECKED_RATIO:
            row_key = round(cb["cy"] / 25) * 25  # group by ~25px row bands
            row_groups[row_key].append(i)

    for row_key, indices in row_groups.items():
        if len(indices) < 2:
            continue
        # Get the ratios for each box in this pair
        pair = [(i, checkboxes[i].get("_ratio", 0)) for i in indices]
        if not any(r > 0 for _, r in pair):
            continue
        max_idx = max(pair, key=lambda x: x[1])[0]
        # Only mark the highest-ratio one as checked, uncheck the others
        for i, _ in pair:
            checkboxes[i]["checked"] = (i == max_idx and checkboxes[i].get("_ratio", 0) > FORM_FIELD_RATIO)

    # Clean up internal _ratio field
    for cb in checkboxes:
        cb.pop("_ratio", None)

    checkboxes.sort(key=lambda c: (c["y"], c["x"]))
    checked_count = sum(c["checked"] for c in checkboxes)
    print(f"  [checkbox_detector] Page {page + 1}: "
          f"{len(checkboxes)} anchor(s) inspected, "
          f"{checked_count} checked.")
    return checkboxes