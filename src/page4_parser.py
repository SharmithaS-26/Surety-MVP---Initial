"""
page4_parser.py
Parses Page 4 of the Built Right CQ scanned form.

Sections:
  • Bond Required Documents checklist  (10 items, each with a checkbox)
  • Signature section  (Signature, Printed Name, Date)
"""

from .utils import (
    cluster_rows, find_row, after_kw,
    tokens_in_region, join_row_tokens,
    checkboxes_in_region, checkbox_on_row,
    resolve_yn_from_checkboxes,
    clean_text, page_width, page_height, row_cy, row_text,
)

# Canonical bond document item labels (used as fallback if OCR misses them)
BOND_ITEMS_CANONICAL = [
    "Year End 12/31 Financial Statement, CPA preferred if available",
    "Most recently reconciled month end accrual financial statements "
    "(Balance Sheet, Profit & Loss, Accounts Receivable Reports, Accounts Payable Reports)",
    "Work in Process (WIP)",
    "Bank Reference Form",
    "Copy of Bank Line of Credit agreement, if available",
    "Personal Financial Statement for all owners",
    "Last 3 Corporate tax Returns",
    "Resumes of owners and key personnel, if available",
    "Letters of recommendation, if available",
    "Business Plan, if available",
]

CHECKLIST_Y_FRAC = (0.05, 0.72)
SIG_Y_FRAC       = (0.72, 1.00)


# ── Bond checklist ─────────────────────────────────────────────────────────────

def _parse_bond_checklist(tokens, boxes, ph, pw):
    y1 = int(CHECKLIST_Y_FRAC[0] * ph)
    y2 = int(CHECKLIST_Y_FRAC[1] * ph)

    cl_boxes = sorted(
        checkboxes_in_region(boxes, 0, y1, pw, y2),
        key=lambda b: b["cy"]
    )
    cl_toks = tokens_in_region(tokens, 0, y1, pw, y2)

    items = []
    for box in cl_boxes:
        # Collect tokens to the right of and vertically near this checkbox
        label_toks = sorted(
            [t for t in cl_toks
             if t["x"] >= box["x2"] - 5
             and t["cy"] >= box["cy"] - 20
             and t["cy"] <= box["cy"] + 35],
            key=lambda t: (t["cy"], t["x"])
        )
        label = clean_text(join_row_tokens(label_toks))

        if not label and len(items) < len(BOND_ITEMS_CANONICAL):
            label = BOND_ITEMS_CANONICAL[len(items)]

        items.append({"item": label, "checked": box["checked"]})

    if not items:
        items = [{"item": name, "checked": False}
                 for name in BOND_ITEMS_CANONICAL]

    return items


# ── Signature section ──────────────────────────────────────────────────────────

def _parse_signature(tokens, ph, pw):
    y1 = int(SIG_Y_FRAC[0] * ph)
    y2 = int(SIG_Y_FRAC[1] * ph)

    sig_toks  = tokens_in_region(tokens, 0, y1, pw, y2)
    all_rows  = cluster_rows(sig_toks)

    signature = printed_name = date = ""
    for row in all_rows:
        rt = row_text(row).lower()
        if "signature" in rt:
            signature = clean_text(after_kw(row, "Signature"))
        elif "printed" in rt or ("name" in rt and "printed" in rt):
            printed_name = clean_text(after_kw(row, "Name"))
        elif "date" in rt:
            date = clean_text(after_kw(row, "Date"))

    return {
        "signature":    signature,
        "printed_name": printed_name,
        "date":         date,
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def parse_page4(tokens: list[dict], boxes: list[dict]) -> dict:
    print("  [page4_parser] Parsing Page 4…")

    pw = page_width(tokens)
    ph = page_height(tokens)

    bond_checklist = _parse_bond_checklist(tokens, boxes, ph, pw)
    signature      = _parse_signature(tokens, ph, pw)

    print(f"  [page4_parser] Done. {len(bond_checklist)} checklist items.")
    return {
        "bond_required_documents": bond_checklist,
        "signature_section":       signature,
    }