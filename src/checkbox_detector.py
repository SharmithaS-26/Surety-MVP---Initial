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
    # e.g. "☐ Yes" → "Yes", "Yes |" → "Yes"
    t_clean = t.lstrip("☐☑✓| ").rstrip("| ").strip()
    if t_clean.lower() in ALL_ANCHOR_LABELS:
        return True
    # Also handle "Yes |" pattern from PyMuPDF
    for label in ALL_ANCHOR_LABELS:
        if t_clean.lower().startswith(label):
            return True
    return False


def _dark_ratio(img_array: np.ndarray) -> float:
    
    if img_array.size == 0:
        return 0.0
    gray = img_array if img_array.ndim == 2 else np.mean(img_array, axis=2)
    return float(np.sum(gray < DARK_THRESHOLD)) / gray.size


def _inspect_region(image: Image.Image,
                     label_x: int, label_cy: int,
                     page_w: int) -> tuple[bool, str, tuple]:
    
    
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
            image, label_x, tok["cy"], pw
        )
        x1, y1, x2, y2 = bbox

        # Store cleaned label (strip ☐/☑ prefix) for Yes/No resolution
        clean_label = tok["text"].strip().lstrip("☐☑✓| ").rstrip("| ").strip()
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
        })

    checkboxes.sort(key=lambda c: (c["y"], c["x"]))
    checked_count = sum(c["checked"] for c in checkboxes)
    print(f"  [checkbox_detector] Page {page + 1}: "
          f"{len(checkboxes)} anchor(s) inspected, "
          f"{checked_count} checked.")
    return checkboxes