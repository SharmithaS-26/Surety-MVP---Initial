"""
page3_parser.py  (robust)
Parses Page 3 of the Built Right CQ scanned form.

Sections:
  • Banking
  • Project Experience  (5 largest completed contracts, 2-row entries)
  • References          (3 sub-tables: Subcontractors, Owners & Architects, Suppliers)

All table parsing uses adaptive row clustering — no hard-coded Y values.
Section boundaries are found by keyword scanning the token stream.
Project entries are anchored by number tokens (1. / 2. / … / 5.).
Reference sub-tables are located by their header keywords.
"""

import re
from .utils import (
    cluster_rows, find_row, after_kw, between_kw,
    tokens_in_region, join_row_tokens,
    checkboxes_in_region, checkbox_on_row,
    resolve_yn_from_checkboxes, yn_from_row,
    clean_text, page_width, page_height, row_cy, row_text,
    toks_in_x_band,
)


def _extract(tokens, *keywords, stop_keywords=None):
    """Extract value after keyword, handling merged label:value tokens."""
    rows = _cluster(tokens)
    stop_kws = [k.lower() for k in (stop_keywords or [])]
    for kw in keywords:
        for row in rows:
            rt = row_text(row).lower()
            if kw.lower() not in rt:
                continue
            full = row_text(row)
            idx = full.lower().find(kw.lower())
            after = full[idx + len(kw):]
            after = re.sub(r'^[\s:*|]+', '', after)
            if stop_kws:
                for sk in stop_kws:
                    si = after.lower().find(sk)
                    if si >= 0:   # >= 0 catches stop kw at start of result too
                        after = after[:si]
                        break
            result = clean_text(after)
            if result:
                return result
    return ""



ROW_CLUSTER_GAP      = 14


def _dedup_words(text: str) -> str:
    """Remove consecutive duplicate words: 'Foo Foo Bar Bar' → 'Foo Bar'"""
    if not text:
        return text
    words = text.split()
    result = [words[0]] if words else []
    for w in words[1:]:
        if w != result[-1]:
            result.append(w)
    return " ".join(result)
PROJECT_ROW_PAIR_GAP = 120  # increased: Row B (contact) can be far below Row A at 300 DPI

# Page-fraction bands
BANKING_Y_FRAC = (0.03, 0.24)
PROJECT_Y_FRAC = (0.24, 0.56)
REF_Y_FRAC     = (0.56, 1.00)

# Project table column x-fractions
PROJ_COL = {
    "name":   (0.00, 0.63),
    "year":   (0.63, 0.72),
    "price":  (0.72, 0.86),
    "profit": (0.86, 1.00),
}

# Reference table column x-fractions
REF_COL = {
    "company": (0.00, 0.50),
    "phone":   (0.50, 0.72),
    "contact": (0.72, 1.00),
}

# Reference section header keywords
REF_SECTION_KWS = {
    "major_subcontractors":  ["subcontractor", "general contractor"],
    "owners_and_architects": ["owners", "architect"],
    "suppliers":             ["supplier"],
}

REF_SKIP_KWS  = ["name of company", "phone number", "contact person"]
PROJ_SKIP_KWS = [
    "project and location", "year complete", "final contract",
    "gross profit", "for whom", "please list", "largest completed",
]

_NUM_RE = re.compile(r"^([1-5])[.\)]?$")


def _cluster(tokens, gap=ROW_CLUSTER_GAP):
    return cluster_rows(tokens, gap)


def _is_skip(text, extra=None):
    kws = PROJ_SKIP_KWS + (extra or [])
    return any(kw in text.lower() for kw in kws)


def _is_num_row(row):
    """
    Detect project number rows. Handles:
    - Separate tokens: ["1.", "FDOT"] 
    - Merged tokens:   ["1.FDOT"] or ["1. FDOT"]
    """
    if not row:
        return False, ""
    first = row[0]["text"].strip()
    # Case 1: token is just the number "1." or "1"
    m = _NUM_RE.match(first.rstrip("."))
    if m:
        return True, m.group(1)
    # Case 2: merged "1.FDOT" — starts with digit then dot
    if len(first) >= 2 and first[0].isdigit() and first[1] in ".)" and first[0] in "12345":
        return True, first[0]
    return False, ""


# ── Banking ────────────────────────────────────────────────────────────────────

def _parse_banking(tokens, boxes, ph, pw):
    y1 = int(BANKING_Y_FRAC[0] * ph)
    y2 = int(BANKING_Y_FRAC[1] * ph)
    bank_toks = tokens_in_region(tokens, 0, y1, pw, y2)
    rows = _cluster(bank_toks)

    # Use _extract which handles merged "Name of Bank: Bank of Tampa" tokens
    bank_name    = _extract(bank_toks, "Name of Bank", stop_keywords=["Contact"])
    contact_name = _extract(bank_toks, "Contact Name")
    bank_address = _extract(bank_toks, "Bank Address", "Bank Addr")
    bank_phone   = _extract(bank_toks, "Bank Phone", stop_keywords=["Contract Email", "Contract", "Email"])
    bank_email   = ""
    for tok in bank_toks:
        if "@" in tok["text"]:
            bank_email = tok["text"]
            break
    how_secured  = _extract(bank_toks, "How is it Secured", "Secured")
    total_loc    = _extract(bank_toks, "Total Line of Credit", stop_keywords=["Amount"])
    avail_loc    = _extract(bank_toks, "Amount Available", stop_keywords=["Expires"])
    expires      = _extract(bank_toks, "Expires")

    # Line of credit Yes/No
    loc_yn = None
    for row in rows:
        rt = row_text(row).lower()
        if "line of credit" in rt or "working line" in rt:
            loc_yn = resolve_yn_from_checkboxes(
                checkbox_on_row(boxes, row_cy(row), tolerance=22)
            )
            break

    # Clean $ signs
    total_loc = total_loc.lstrip("$").strip()
    avail_loc = avail_loc.lstrip("$").strip()
    expires   = expires.lstrip("$").strip()

    # Dummy block to satisfy old code structure

    return {
        "bank_name":            clean_text(bank_name),
        "contact_name":         clean_text(contact_name),
        "bank_address":         clean_text(bank_address),
        "bank_phone":           clean_text(bank_phone),
        "bank_email":           clean_text(bank_email),
        "line_of_credit":       loc_yn,
        "total_line_of_credit": clean_text(total_loc),
        "amount_available":     clean_text(avail_loc),
        "expires":              clean_text(expires),
        "how_secured":          clean_text(how_secured),
    }


# ── Project Experience ─────────────────────────────────────────────────────────

def _parse_projects(tokens, ph, pw):
    y1 = int(PROJECT_Y_FRAC[0] * ph)
    y2 = int(PROJECT_Y_FRAC[1] * ph)
    proj_toks = tokens_in_region(tokens, 0, y1, pw, y2)
    rows = _cluster(proj_toks)

    projects, i = [], 0
    while i < len(rows):
        row = rows[i]
        rt  = row_text(row)

        if _is_skip(rt):
            i += 1
            continue

        is_num, digit = _is_num_row(row)
        if is_num:
            # PyMuPDF places the number token ("1.") BELOW the data tokens
            # (FDOT, 2025, $10MM are at cy=933, "1." is at cy=949)
            # So look for data in: (1) this row, (2) the row immediately ABOVE
            data_row = row
            num_cy   = row_cy(row)

            if i > 0:
                prev_row = rows[i - 1]
                prev_cy  = row_cy(prev_row)
                # If previous row is within 25px above and has data columns
                if 0 < num_cy - prev_cy <= 25 and not _is_skip(row_text(prev_row)):
                    is_prev_num, _ = _is_num_row(prev_row)
                    if not is_prev_num:
                        data_row = prev_row  # use the row above as data source

            import re as _re
            name_toks   = toks_in_x_band(data_row, *PROJ_COL["name"],   pw)
            year_toks   = toks_in_x_band(data_row, *PROJ_COL["year"],   pw)
            price_toks  = toks_in_x_band(data_row, *PROJ_COL["price"],  pw)
            profit_toks = toks_in_x_band(data_row, *PROJ_COL["profit"], pw)

            # Strip leading digit token from name
            name_toks = [t for t in name_toks
                         if not _NUM_RE.match(t["text"].strip().rstrip("."))]

            # Clean project name
            raw_name = clean_text(join_row_tokens(name_toks))
            raw_name = _re.sub(r'^[1-5][.)\s]+', '', raw_name).strip()
            raw_name_words = raw_name.split()
            raw_name_dedup = []
            for w in raw_name_words:
                if not raw_name_dedup or w != raw_name_dedup[-1]:
                    raw_name_dedup.append(w)
            raw_name = " ".join(raw_name_dedup)

            # Clean year
            raw_year = clean_text(join_row_tokens(year_toks))
            year_match = _re.search(r'(20\d{2}|19\d{2})', raw_year)
            raw_year = year_match.group(1) if year_match else raw_year

            entry = {
                "project_number":       digit,
                "project_name":         raw_name,
                "year_complete":        raw_year,
                "final_contract_price": clean_text(join_row_tokens(price_toks)).lstrip("$").strip(),
                "gross_profit":         clean_text(join_row_tokens(profit_toks)).lstrip("$").strip(),
                "for_whom_contact":     "",
            }

            # Look ahead for the contact row (Row B)
            j = i + 1
            while j < len(rows):
                nrow = rows[j]
                nrt  = row_text(nrow)
                if _is_skip(nrt):
                    j += 1
                    continue
                is_next_num, _ = _is_num_row(nrow)
                if is_next_num:
                    break
                if row_cy(nrow) - row_cy(row) > PROJECT_ROW_PAIR_GAP:
                    break
                entry["for_whom_contact"] = clean_text(nrt)
                i = j
                break

            projects.append(entry)

        i += 1

    return projects[:5]


# ── References ─────────────────────────────────────────────────────────────────

def _parse_one_ref_table(tokens, y1, y2, pw):
    region = tokens_in_region(tokens, 0, y1, pw, y2)
    rows   = _cluster(region)
    entries = []

    for row in rows:
        rt = row_text(row).lower()
        if any(kw in rt for kw in REF_SKIP_KWS):
            continue
        if any(kw in rt for kw in
               ["major subcontractor", "general contractor",
                "owners & architect", "owners and architect", "supplier"]):
            continue

        # Use cx (center) for column assignment — more robust than x/x2 edges
        company = clean_text(join_row_tokens(
            [t for t in row if t["cx"] <= pw * REF_COL["company"][1]]))
        phone   = clean_text(join_row_tokens(
            [t for t in row if pw * REF_COL["phone"][0] < t["cx"] <= pw * REF_COL["phone"][1]]))
        contact = clean_text(join_row_tokens(
            [t for t in row if t["cx"] > pw * REF_COL["contact"][0]]))

        if company or contact:
            entries.append({
                "company": _dedup_words(company),
                "phone":   phone,
                "contact": _dedup_words(contact),
            })

    return entries


def _parse_references(tokens, ph, pw):
    y1_ref = int(REF_Y_FRAC[0] * ph)
    y2_ref = int(REF_Y_FRAC[1] * ph)

    ref_toks = tokens_in_region(tokens, 0, y1_ref, pw, y2_ref)
    rows     = _cluster(ref_toks)

    header_ys = {}
    for row in rows:
        rt = row_text(row).lower()
        for section, kws in REF_SECTION_KWS.items():
            if section not in header_ys and any(kw in rt for kw in kws):
                header_ys[section] = row_cy(row)

    h = y2_ref - y1_ref
    sub_y1 = header_ys.get("major_subcontractors",  y1_ref)
    oa_y1  = header_ys.get("owners_and_architects", sub_y1 + int(h * 0.38))
    sup_y1 = header_ys.get("suppliers",             oa_y1  + int(h * 0.30))

    return {
        "major_subcontractors":  _parse_one_ref_table(tokens, sub_y1, oa_y1,  pw),
        "owners_and_architects": _parse_one_ref_table(tokens, oa_y1,  sup_y1, pw),
        "suppliers":             _parse_one_ref_table(tokens, sup_y1, y2_ref, pw),
    }


# ── Main entry point ───────────────────────────────────────────────────────────

def parse_page3(tokens: list[dict], boxes: list[dict]) -> dict:
    print("  [page3_parser] Parsing Page 3…")

    pw = page_width(tokens)
    ph = page_height(tokens)

    banking    = _parse_banking(tokens, boxes, ph, pw)
    projects   = _parse_projects(tokens, ph, pw)
    references = _parse_references(tokens, ph, pw)

    print(f"  [page3_parser] Done. "
          f"{len(projects)} projects | "
          f"{len(references['major_subcontractors'])} subcontractors | "
          f"{len(references['owners_and_architects'])} owners/arch | "
          f"{len(references['suppliers'])} suppliers")

    return {
        "banking":    banking,
        "projects":   projects,
        "references": references,
    }