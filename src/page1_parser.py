"""
page1_parser.py
Parses Page 1 of the Built Right CQ scanned form.

KEY LESSONS from token dump analysis:
  1. EasyOCR often puts the VALUE token ABOVE the LABEL token in Y coordinate
     (value is in larger/bolder font, rendered at slightly higher position)
  2. Label and value are sometimes separate tokens, sometimes merged
  3. Contact name "Butch Taylor, Jr." may be missed entirely or merged
  
Strategy: for each field, search ALL tokens within a Y-proximity band
of the label token, looking both above and below.
"""

import re
from .utils import (
    cluster_rows, find_row, join_row_tokens,
    tokens_in_region, tokens_on_row,
    checkbox_on_row, resolve_yn_from_checkboxes,
    checked_labels, yn_from_row,
    clean_text, page_width, page_height, row_cy, row_text,
)

COL_SPLIT_FRAC  = 0.50
OWNER_ROW_FRACS = [(0.38, 0.62), (0.63, 0.87)]


# ── Universal value extractor ─────────────────────────────────────────────────

def _find_label_token(tokens, *keywords):
    """Find the first token whose text contains any of the given keywords."""
    for kw in keywords:
        for tok in tokens:
            if kw.lower() in tok["text"].lower():
                return tok
    return None


def _extract(tokens, *keywords, stop_keywords=None, search_above=True):
    """
    Extract value associated with a label keyword.
    
    Searches for a token containing the keyword, then extracts:
    1. Everything after the keyword in the same token (merged case)
    2. Tokens to the RIGHT on the same row
    3. Tokens ABOVE the label (value rendered higher due to larger font)
    
    Args:
        search_above: Also look at tokens with cy slightly above the label token
    """
    stop_kws = [k.lower() for k in (stop_keywords or [])]
    all_rows = cluster_rows(tokens)
    
    for kw in keywords:
        label_tok = _find_label_token(tokens, kw)
        if not label_tok:
            continue
        
        label_cy = label_tok["cy"]
        label_x  = label_tok["x"]
        label_x2 = label_tok["x2"]
        
        # Strategy 1: value is in the same token after the keyword
        full = label_tok["text"]
        kw_idx = full.lower().find(kw.lower())
        if kw_idx != -1:
            after = full[kw_idx + len(kw):]
            after = re.sub(r'^[\s:*|?]+', '', after)
            if stop_kws:
                for sk in stop_kws:
                    si = after.lower().find(sk)
                    if si > 0:
                        after = after[:si]
            if clean_text(after):
                return clean_text(after)
        
        # Strategy 2: tokens to the right on the same row (within 15px vertically)
        right_toks = sorted(
            [t for t in tokens 
             if t["x"] > label_x2 
             and abs(t["cy"] - label_cy) <= 15
             and t["text"].strip().lower() not in {kw.lower()}],
            key=lambda t: t["x"]
        )
        if right_toks:
            val = join_row_tokens(right_toks)
            if stop_kws:
                for sk in stop_kws:
                    si = val.lower().find(sk)
                    if si > 0:
                        val = val[:si]
            if clean_text(val):
                return clean_text(val)
        
        # Strategy 3: token ABOVE the label (value in larger font, higher cy)
        if search_above:
            above_toks = sorted(
                [t for t in tokens
                 if t["cy"] < label_cy 
                 and abs(t["cy"] - label_cy) <= 30
                 and abs(t["cx"] - label_tok["cx"]) <= 700],
                key=lambda t: abs(t["cy"] - label_cy)
            )
            for at in above_toks:
                v = clean_text(at["text"])
                if v and v.lower() not in {kw.lower(), "company name:", "address:"}:
                    return v
    
    return ""


def _extract_between(tokens, start_kw, end_kw):
    """Extract text between two keywords on the same row."""
    label_tok = _find_label_token(tokens, start_kw)
    if not label_tok:
        return ""
    
    cy  = label_tok["cy"]
    row = sorted(
        [t for t in tokens if abs(t["cy"] - cy) <= 15],
        key=lambda t: t["x"]
    )
    
    full = join_row_tokens(row)
    s = full.lower().find(start_kw.lower())
    e = full.lower().find(end_kw.lower()) if end_kw else len(full)
    
    if s == -1:
        return ""
    
    chunk = full[s + len(start_kw): e if (e != -1 and e > s) else len(full)]
    chunk = re.sub(r'^[\s:*|?$]+', '', chunk)
    return clean_text(chunk)


def _yn(tokens, boxes, *keywords, dy=25):
    """Resolve Yes/No for a row containing any of the keywords."""
    all_rows = cluster_rows(tokens)
    for kw in keywords:
        row = find_row(all_rows, kw)
        if row:
            val = yn_from_row(row, boxes, dy=dy)
            if val:
                return val
    return None


# ── Owner extraction ──────────────────────────────────────────────────────────

def _extract_owner(tokens, boxes, y1, y2, x1, x2):
    """Extract one owner slot from a pixel region."""
    region = tokens_in_region(tokens, x1, y1, x2, y2)
    if not region:
        return {}
    
    all_rows = cluster_rows(region)
    
    def near(cy_target, dy=20):
        """Tokens within dy pixels of cy_target, sorted left to right."""
        return sorted(
            [t for t in region if abs(t["cy"] - cy_target) <= dy],
            key=lambda t: t["x"]
        )
    
    def val_in_row(row, skip_kws):
        """Join tokens in row that don't match skip keywords."""
        return join_row_tokens(
            [t for t in row if t["text"].strip().lower() not in skip_kws]
        )
    
    # ── Name ──
    # PyMuPDF: the value "Butch Taylor, Sr." is often ABOVE the "Name" label row
    # because filled-form text renders above the label baseline
    name_val = ""
    name_label_cy = None
    for i, row in enumerate(all_rows):
        rt = row_text(row).lower().strip()
        if rt == "name" or rt == "name name":
            name_label_cy = row_cy(row)
            # Look for a value token in the row ABOVE (within 30px)
            if i > 0:
                prev_row = all_rows[i - 1]
                prev_rt = row_text(prev_row).lower()
                if not any(kw in prev_rt for kw in ["name","title","address","city","dob","ssn","spouse"]):
                    val_toks = [t for t in prev_row if t["text"].strip().lower() not in {"name"}]
                    candidate = join_row_tokens(val_toks)
                    if candidate and len(candidate) > 3:
                        name_val = candidate
                        break
            continue
        if "name" in rt and name_label_cy is None:
            val_toks = [t for t in row if t["text"].strip().lower() != "name"]
            candidate = join_row_tokens(val_toks)
            if candidate and not any(kw in candidate.lower()
                                      for kw in ["title", "address", "ownership", "city"]):
                name_val = candidate
                break
    
    # ── Title / Ownership% ──
    title_val, pct_val = "", ""
    for row in all_rows:
        rt = row_text(row).lower()
        if "title" in rt and ("%" in rt or "ownership" in rt):
            full = row_text(row)
            t_idx = full.lower().find("title")
            if t_idx != -1:
                rest = full[t_idx + 5:].strip().lstrip(":")
                for stop in ["%", "Ownership", "ownership"]:
                    si = rest.find(stop)
                    if si > 0:
                        rest = rest[:si]
                title_val = clean_text(rest)
            # Ownership %
            for kw in ["Ownership", "ownership"]:
                oi = full.lower().find(kw)
                if oi != -1:
                    candidate = full[oi + len(kw):].strip().split()
                    if candidate:
                        pct_val = candidate[0]
            break
    
    # ── Address ──
    addr_val = ""
    for row in all_rows:
        rt = row_text(row).lower()
        if rt.strip() == "address":
            # Value may be in same row or next row
            idx = all_rows.index(row)
            if idx + 1 < len(all_rows):
                next_row = all_rows[idx + 1]
                if "city" not in row_text(next_row).lower():
                    addr_val = val_in_row(next_row, {"address"})
            break
        elif "address" in rt and len(rt) > 10:
            full = row_text(row)
            ai = full.lower().find("address")
            chunk = full[ai + 7:].strip().lstrip(":")
            if clean_text(chunk) and "city" not in chunk.lower():
                addr_val = clean_text(chunk)
            break
    
    # ── City/State/Zip ──
    csz_val = ""
    for row in all_rows:
        rt = row_text(row).lower()
        if "city" in rt and "state" in rt:
            full = row_text(row)
            ci = full.lower().find("city")
            chunk = full[ci:].strip()
            for skip in ["City*State*Zip", "City State Zip"]:
                chunk = chunk.replace(skip, "").replace(skip.lower(), "")
            chunk = re.sub(r'^[\s*:]+', '', chunk)
            csz_val = clean_text(chunk)
            break
    
    # ── DOB / SSN ──
    dob_val = ssn_val = ""
    sdob_val = sssn_val = ""
    spouse_val = ""
    dob_found = False
    
    # DOB/SSN extraction - handles both merged tokens and separate rows
    # PyMuPDF often puts value tokens 3-5pt ABOVE their label tokens
    for row in all_rows:
        rt = row_text(row).lower()
        if "dob" in rt and "ssn" in rt and len(rt) > 5:
            # Merged row like "DOB 5/10/1950 SSN 786-52-0912"
            full = row_text(row)
            d_idx = full.upper().find("DOB")
            s_idx = full.upper().find("SSN")
            if d_idx != -1 and s_idx != -1 and s_idx > d_idx:
                dob_chunk = full[d_idx + 3: s_idx].strip().strip(":").strip()
                ssn_chunk  = full[s_idx + 3:].strip().strip(":").split()
                # Only count as values if dob_chunk has actual content (not just whitespace)
                if dob_chunk and len(dob_chunk) > 2:
                    if not dob_found:
                        dob_val = clean_text(dob_chunk)
                        ssn_val = clean_text(ssn_chunk[0]) if ssn_chunk else ""
                        dob_found = True
                    else:
                        sdob_val = clean_text(dob_chunk)
                        sssn_val = clean_text(ssn_chunk[0]) if ssn_chunk else ""
                # If no value in merged token, fall through to proximity search below
        elif "dob" in rt and len(rt) < 25:
            # DOB label row - look for value tokens nearby (above or below, ±25px)
            dob_cy = row_cy(row)
            val_toks = sorted(
                [t for t in region
                 if abs(t["cy"] - dob_cy) <= 25
                 and t["x"] > row[0]["x2"]
                 and t["text"].strip().lower() not in ("dob","ssn","spouse","address","city*state*zip","city","name","title")
                 and len(t["text"].strip()) > 2],
                key=lambda t: t["x"]
            )
            if val_toks and not dob_found:
                dob_val = val_toks[0]["text"]
                # SSN is the next token
                ssn_toks = [t for t in region
                            if abs(t["cy"] - dob_cy) <= 25
                            and t["x"] > val_toks[0]["x2"]
                            and t["text"].strip().lower() not in ("dob","ssn")]
                if ssn_toks:
                    ssn_val = ssn_toks[0]["text"]
                dob_found = True
            elif val_toks and dob_found and not sdob_val:
                sdob_val = val_toks[0]["text"]
                ssn_toks = [t for t in region
                            if abs(t["cy"] - dob_cy) <= 25
                            and t["x"] > val_toks[0]["x2"]
                            and t["text"].strip().lower() not in ("dob","ssn")]
                if ssn_toks:
                    sssn_val = ssn_toks[0]["text"]
        elif "spouse" in rt:
            full = row_text(row)
            sp_idx = full.lower().find("spouse")
            after = full[sp_idx + 6:].strip().strip(":")
            if clean_text(after):
                spouse_val = clean_text(after)
            elif not spouse_val:
                # Spouse name may be on a nearby row (above the label)
                sp_cy = row_cy(row)
                nearby = [t for t in region
                          if abs(t["cy"] - sp_cy) <= 25
                          and t["x"] > 50
                          and t["text"].strip().lower() not in
                          ("spouse","dob","ssn","name","title","address","city")]
                if nearby:
                    spouse_val = clean_text(join_row_tokens(
                        sorted(nearby, key=lambda t: t["x"])
                    ))
    
    owner = {
        "name":           clean_text(name_val),
        "title":          clean_text(title_val),
        "ownership_pct":  clean_text(pct_val),
        "address":        clean_text(addr_val),
        "city_state_zip": clean_text(csz_val),
        "dob":            clean_text(dob_val),
        "ssn":            clean_text(ssn_val),
        "spouse": {
            "name": clean_text(spouse_val),
            "dob":  clean_text(sdob_val),
            "ssn":  clean_text(sssn_val),
        }
    }
    # Reject heading rows falsely captured as owner names
    invalid_kws = ["corporate", "stockholder", "indemnitor", "information",
                   "will all owners", "if no, why"]
    if any(kw in owner["name"].lower() for kw in invalid_kws):
        return {}
    return owner if owner["name"] else {}


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_page1(tokens: list[dict], boxes: list[dict]) -> dict:
    print("  [page1_parser] Parsing Page 1…")

    pw       = page_width(tokens)
    ph       = page_height(tokens)
    all_rows = cluster_rows(tokens)

    # ── General Information ────────────────────────────────────────────────────

    # Company name — value token is often ABOVE the label token
    company_name = _extract(tokens, "Company Name", search_above=True)
    
    # Address — between "Address:" and "Phone"
    address = _extract_between(tokens, "Address:", "Phone")
    if not address:
        address = _extract(tokens, "Address:", stop_keywords=["Phone"])
    
    # Phone — find "Phone No" label then get value token to its right (within 30px vertically)
    phone = _extract(tokens, "Phone No.:", "Phone No:", "Phone No")
    if not phone:
        label_tok = _find_label_token(tokens, "Phone No")
        if label_tok:
            # Look right AND slightly above/below (PyMuPDF y can vary by a few px)
            row_toks = sorted(
                [t for t in tokens
                 if t["x"] > label_tok["x2"]
                 and abs(t["cy"] - label_tok["cy"]) <= 25
                 and t["text"].strip() not in ("", ":", "|")],
                key=lambda t: t["x"]
            )
            phone = join_row_tokens(row_toks)
    
    # Primary contact — "Primary Contact:" label, value to the right or nearby
    primary_contact = ""
    email = ""
    label_tok = _find_label_token(tokens, "Primary Contact")
    if label_tok:
        cy = label_tok["cy"]
        # Value tokens: to the right of the label, not containing "Email"
        contact_toks = sorted(
            [t for t in tokens
             if abs(t["cy"] - cy) <= 15
             and t["x"] > label_tok["x2"]
             and "email" not in t["text"].lower()
             and "@" not in t["text"]],
            key=lambda t: t["x"]
        )
        primary_contact = join_row_tokens(contact_toks)
        # Email — look for @ token near this row
        at_toks = [t for t in tokens if "@" in t["text"]
                   and abs(t["cy"] - cy) <= 30]
        if at_toks:
            email = at_toks[0]["text"]
    
    if not email:
        for tok in tokens:
            if "@" in tok["text"]:
                email = tok["text"]
                break
    # Strip "Email Address:" prefix if OCR included it
    if email and "email" in email.lower() and ":" in email:
        idx = email.find(":")
        email = email[idx+1:].strip()
    # Strip "Address:" prefix
    if email and email.lower().startswith("address:"):
        email = email[8:].strip()

    # Business type checkboxes
    biz_type_row = find_row(all_rows, "Type of Business")
    business_types = checked_labels(biz_type_row, boxes, max_dx=200)

    # Date started
    date_started = _extract_between(tokens, "Date Business Started", "Fed Tax")
    if not date_started:
        date_started = _extract(tokens, "Date Business Started")
    # Clean OCR noise from date — keep only digits and /
    if date_started:
        date_clean = re.sub(r'[^0-9/]', '', date_started)
        if len(date_clean) >= 4:
            date_started = date_clean

    # Fed Tax ID
    fed_tax_id = _extract_between(tokens, "Fed Tax ID", "")
    if not fed_tax_id:
        fed_tax_id = _extract(tokens, "Fed Tax ID")
    # Strip "#: " prefix if OCR/PyMuPDF included it
    import re as _re2
    fed_tax_id = _re2.sub(r'^[#:\s]+', '', fed_tax_id).strip()

    # NAICS code
    naics_code = _extract_between(tokens, "NAICS Code", "Number")
    if not naics_code:
        naics_code = _extract(tokens, "Primary NAICS Code", "NAICS Code")
    # Keep only digits
    if naics_code:
        naics_clean = re.sub(r'[^0-9]', '', naics_code)
        if naics_clean:
            naics_code = naics_clean

    # Number of employees
    employees = _extract_between(tokens, "Number of Employees", "")
    if not employees:
        employees = _extract(tokens, "Number of Employees", "Employees:")
    # Keep only digits
    if employees:
        emp_clean = re.sub(r'[^0-9]', '', employees)
        if emp_clean:
            employees = emp_clean

    # Special designations
    desig_row = find_row(all_rows, "Special Designations")
    special_designations = checked_labels(desig_row, boxes, max_dx=150)

    general_information = {
        "company_name":          clean_text(company_name),
        "address":               clean_text(address),
        "phone":                 clean_text(phone),
        "primary_contact":       clean_text(primary_contact),
        "email":                 clean_text(email),
        "type_of_business":      business_types,
        "date_business_started": date_started,
        "fed_tax_id":            clean_text(fed_tax_id),
        "primary_naics_code":    naics_code,
        "number_of_employees":   employees,
        "special_designations":  special_designations,
    }

    # ── Corporate Officers ─────────────────────────────────────────────────────
    owners = []
    col_split = int(pw * COL_SPLIT_FRAC)

    for y_frac_start, y_frac_end in OWNER_ROW_FRACS:
        y1 = int(ph * y_frac_start)
        y2 = int(ph * y_frac_end)
        left  = _extract_owner(tokens, boxes, y1, y2, 0,         col_split)
        right = _extract_owner(tokens, boxes, y1, y2, col_split, pw)
        if left:
            owners.append(left)
        if right:
            owners.append(right)

    # ── Personal indemnification ───────────────────────────────────────────────
    indemn_row = (find_row(all_rows, "indemnification")
                  or find_row(all_rows, "surety", "spouses")
                  or find_row(all_rows, "owners", "spouses"))
    indemn_val = yn_from_row(indemn_row, boxes, dy=25)

    print(f"  [page1_parser] Done. {len(owners)} owner(s) found.")
    return {
        "general_information":      general_information,
        "owners":                   owners,
        "personal_indemnification": indemn_val,
    }