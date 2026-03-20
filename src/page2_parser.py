
import re
from .utils import (
    cluster_rows, find_row, after_kw, between_kw,
    tokens_in_region, join_row_tokens,
    checkboxes_in_region, checkbox_on_row,
    resolve_yn_from_checkboxes, checked_labels, yn_from_row,
    clean_text, page_width, page_height, row_cy, row_text,
)
ROW_CLUSTER_GAP = 14

def _cluster(tokens):
    return cluster_rows(tokens, ROW_CLUSTER_GAP)

def _extract(tokens, *keywords, stop_keywords=None):
    """Find value by searching for keyword in any token, handling merged label:value tokens."""
    all_rows = _cluster(tokens)
    stop_kws = [k.lower() for k in (stop_keywords or [])]
    for kw in keywords:
        for row in all_rows:
            rt = row_text(row).lower()
            if kw.lower() not in rt:
                continue
            full = row_text(row)
            idx = full.lower().find(kw.lower())
            after = full[idx + len(kw):]
            after = re.sub(r'^[\s:*|?]+', '', after)
            if stop_kws:
                for sk in stop_kws:
                    si = after.lower().find(sk)
                    if si > 0:
                        after = after[:si]
            result = clean_text(after)
            if result:
                return result
    return ""

def _extract_between(tokens, start_kw, end_kw):
    all_rows = _cluster(tokens)
    for row in all_rows:
        rt = row_text(row).lower()
        if start_kw.lower() not in rt:
            continue
        full = row_text(row)
        s = full.lower().find(start_kw.lower())
        e = full.lower().find(end_kw.lower()) if end_kw else len(full)
        if s == -1:
            continue
        chunk = full[s + len(start_kw): e if e > s else len(full)]
        chunk = re.sub(r'^[\s:*|?$]+', '', chunk)
        result = clean_text(chunk)
        if result:
            return result
    return ""

def _yn(tokens, boxes, *keywords, dy=35):
    all_rows = _cluster(tokens)
    for kw in keywords:
        row = find_row(all_rows, kw)
        if row:
            val = yn_from_row(row, boxes, dy=dy)
            if val:
                return val
    return None

def _parse_subsidiaries(tokens, boxes, ph, pw):
    all_rows = _cluster(tokens)
    sub_y1, fin_y1 = None, None
    for row in all_rows:
        rt = row_text(row).lower()
        if "subsidiaries" in rt and "affiliates" in rt and sub_y1 is None:
            sub_y1 = row_cy(row)
        if "financial information" in rt and fin_y1 is None:
            fin_y1 = row_cy(row)
    sub_y1 = sub_y1 or int(ph * 0.53)
    fin_y1 = fin_y1 or int(ph * 0.74)
    table_toks  = tokens_in_region(tokens, 0, sub_y1, pw, fin_y1)
    table_rows  = _cluster(table_toks)
    table_boxes = checkboxes_in_region(boxes, int(pw * 0.75), sub_y1, pw, fin_y1)
    table_boxes_s = sorted(table_boxes, key=lambda b: (b["cy"], b["cx"]))
    yn_pairs, i = [], 0
    while i < len(table_boxes_s):
        b = table_boxes_s[i]
        if i + 1 < len(table_boxes_s):
            nb = table_boxes_s[i + 1]
            if abs(nb["cy"] - b["cy"]) <= 25:
                yn_pairs.append((b, nb))
                i += 2
                continue
        yn_pairs.append((b, None))
        i += 1
    skip_kws = ["firm name", "ownership", "type of business", "willing",
                "indemnify", "subsidiaries", "affiliates", "is the firm",
                "holding", "detail below", "financial information"]
    entries, pair_idx = [], 0
    for row in table_rows:
        rt = row_text(row).lower()
        if any(kw in rt for kw in skip_kws) or not rt.strip():
            continue
        firm  = join_row_tokens([t for t in row if t["x2"] <= pw * 0.35])
        pct   = join_row_tokens([t for t in row if pw * 0.35 <= t["x"] < pw * 0.59])
        btype = join_row_tokens([t for t in row if pw * 0.59 <= t["x"] < pw * 0.78])
        indem = None
        if pair_idx < len(yn_pairs):
            cy = row_cy(row)
            yes_b, no_b = yn_pairs[pair_idx]
            if abs(yes_b["cy"] - cy) <= 25:
                chk = [b for b in [yes_b, no_b] if b and b.get("checked")]
                if chk:
                    indem = "Yes" if chk[0].get("label","").lower() == "yes" else "No"
                pair_idx += 1
        if clean_text(firm) or clean_text(pct) or clean_text(btype):
            entries.append({
                "firm_name":            clean_text(firm),
                "ownership_pct":        clean_text(pct),
                "type_of_business":     clean_text(btype),
                "willing_to_indemnify": indem,
            })
    return entries

def parse_page2(tokens, boxes):
    print("  [page2_parser] Parsing Page 2…")
    pw = page_width(tokens)
    ph = page_height(tokens)
    all_rows = _cluster(tokens)
    # ── Business Information ───────────────────────────────────────────────────
    type_of_work = _extract(tokens, "Type of Work Performed", "Work Performed")
    trades_self  = _extract(tokens, "Trades Self Performed")
    trades_sub = _extract(tokens, "Trades Subcontracted")
    # If the string contains its own beginning repeated, deduplicate
    # e.g. "X...Z. X...W" where X is repeated prefix → keep only first sentence
    if trades_sub and len(trades_sub) > 30:
        first20 = trades_sub[:20]
        second_start = trades_sub.find(first20, 10)
        if second_start > 0:
            trades_sub = trades_sub[:second_start].strip()
    # Union / Non-Union
    union_row    = find_row(all_rows, "Non-Union") or find_row(all_rows, "Union")
    union_labels = checked_labels(union_row, boxes, max_dx=180)
    union_status = union_labels[0] if union_labels else None
    geo_territory = _extract_between(tokens, "Geographic Territory", "") or \
                    _extract(tokens, "Geographic Territory")
    # Bid/Negotiated
    bid_pct = _extract_between(tokens, "Bid:", "%")
    neg_pct = _extract_between(tokens, "Negotiated:", "%")
    if not bid_pct:
        bid_pct = _extract(tokens, "Bid:")
    if not neg_pct:
        neg_pct = _extract(tokens, "Negotiated:")
    # Public/Private
    pub_pct  = _extract_between(tokens, "Public:", "%")
    priv_pct = _extract_between(tokens, "Private:", "%")
    # Sub bonds
    sub_bonds_yn = _yn(tokens, boxes, "subcontractors", "bonds")
    sub_bond_threshold = _extract(tokens, "for work over")
    # Backlog
    backlog_cost      = _extract_between(tokens, "Backlog:", "Year")
    backlog_year      = _extract_between(tokens, "Year:", "Number")
    backlog_contracts = _extract(tokens, "Number of Contracts", "Contracts:")
    # Bond program
    single_amt = _extract_between(tokens, "Single $", "Aggregate") or \
                 _extract_between(tokens, "Single", "Aggregate")
    agg_amt    = _extract(tokens, "Aggregate $") or _extract(tokens, "Aggregate")
    # Currently bonded
    bonded_row       = find_row(all_rows, "Currently Bonded")
    currently_bonded = yn_from_row(bonded_row, boxes, dy=25)
    surety_name      = _extract(tokens, "Name of Surety", "Surety:")
    # Yes/No questionnaire rows — search by unique keywords
    failed_contract  = _yn(tokens, boxes, "failed to complete", "bonding company", dy=40)
    bankruptcy       = _yn(tokens, boxes, "bankruptcy")
    judgments        = _yn(tokens, boxes, "judgments", "suits", "claims")
    buy_sell         = _yn(tokens, boxes, "Buy-Sell", "Buy Sell")
    assets_trust     = _yn(tokens, boxes, "assets held in trust", "pledged")
    trust_indemnify  = "N/A" if assets_trust == "No" else \
                       _yn(tokens, boxes, "trust indemnify", "indemnify the surety")
    sub_qn_yn        = _yn(tokens, boxes, "stockholders connected", "subsidiary")
    subsidiaries = _parse_subsidiaries(tokens, boxes, ph, pw)
    business_information = {
        "type_of_work_performed":        clean_text(type_of_work),
        "trades_self_performed":         clean_text(trades_self),
        "trades_subcontracted":          clean_text(trades_sub),
        "union_status":                  union_status,
        "geographic_territory":          clean_text(geo_territory),
        "work_acquired_bid_pct":         clean_text(bid_pct).replace("%","").strip(),
        "work_acquired_negotiated_pct":  clean_text(neg_pct).replace("%","").strip(),
        "work_public_pct":               clean_text(pub_pct).replace("%","").strip(),
        "work_private_pct":              clean_text(priv_pct).replace("%","").strip(),
        "subcontractor_bonds_required":  sub_bonds_yn,
        "sub_bond_threshold":            "" if clean_text(sub_bond_threshold) == "$" else clean_text(sub_bond_threshold),
        "largest_cost_to_complete":      clean_text(backlog_cost),
        "backlog_year":                  clean_text(backlog_year),
        "number_of_contracts":           clean_text(backlog_contracts),
        "desired_bond_single":           clean_text(single_amt),
        "desired_bond_aggregate":        clean_text(agg_amt),
        "currently_bonded":              currently_bonded,
        "surety_name":                   clean_text(surety_name),
        "failed_to_complete_contract":   failed_contract,
        "petitioned_for_bankruptcy":     bankruptcy,
        "judgments_suits_claims":        judgments,
        "buy_sell_agreement":            buy_sell,
        "assets_held_in_trust":          assets_trust,
        "trust_will_indemnify_surety":   trust_indemnify,
        "connected_to_other_company":    sub_qn_yn,
        "subsidiaries_affiliates":       subsidiaries,
    }
    # ── Financial Information ──────────────────────────────────────────────────
    cpa_name    = _extract(tokens, "Name of CPA firm", "CPA firm")
    cpa_address = _extract(tokens, "CPA Address")
    cpa_contact = _extract_between(tokens, "CPA Contact", "Email") or \
                  _extract(tokens, "CPA Contact")
    
    email = ""
    for tok in tokens:
        if "@" in tok["text"] and "cpa" not in tok["text"].lower()[:5]:
            # Get the one on the CPA contact row
            pass
    # Find email token near CPA contact row
    cpa_row = find_row(all_rows, "CPA Contact")
    if cpa_row:
        at_toks = [t for t in cpa_row if "@" in t["text"]]
        raw_email = at_toks[0]["text"] if at_toks else _extract(tokens, "Email Address")
        # Strip "Email Address:" or "Address:" prefix if OCR included it
        if raw_email and ":" in raw_email and "@" in raw_email:
            idx = raw_email.rfind(":") 
            candidate = raw_email[idx+1:].strip()
            email = candidate if "@" in candidate else raw_email
        else:
            email = raw_email
    fiscal_year_end = _extract_between(tokens, "Fiscal Year End", "How") or \
                      _extract(tokens, "Fiscal Year End")
    years_prepared  = _extract(tokens, "financial statement?") or \
                      _extract(tokens, "prepared your financial statement")
    tax_row       = find_row(all_rows, "taxes prepared")
    fin_stmt_row  = find_row(all_rows, "financial statements prepared")
    fin_level_row = find_row(all_rows, "level", "financial statements")
    fulltime_row  = find_row(all_rows, "full-time accountant") or \
                    find_row(all_rows, "full time accountant")
    tax_basis_labels  = checked_labels(tax_row,       boxes, max_dx=200)
    fin_stmt_labels   = checked_labels(fin_stmt_row,  boxes, max_dx=200)
    fin_level_labels  = checked_labels(fin_level_row, boxes, max_dx=200)
    fulltime_acct     = yn_from_row(fulltime_row, boxes, dy=25)
    acct_sw  = _extract(tokens, "Accounting Software")
    est_sw   = _extract(tokens, "Estimating Software")
    jcost_sw = _extract(tokens, "Job Cost Software")
    financial_information = {
        "cpa_firm":                     clean_text(cpa_name),
        "cpa_address":                  clean_text(cpa_address),
        "cpa_contact":                  clean_text(cpa_contact),
        "cpa_email":                    clean_text(email),
        "fiscal_year_end":              clean_text(fiscal_year_end),
        "years_prepared_statements":    clean_text(years_prepared),
        "tax_basis":                    tax_basis_labels,
        "financial_statement_basis":    fin_stmt_labels,
        "financial_statement_level":    fin_level_labels,
        "fulltime_accountant_on_staff": fulltime_acct,
        "accounting_software":          clean_text(acct_sw),
        "estimating_software":          clean_text(est_sw),
        "job_cost_software":            clean_text(jcost_sw),
    }
    print("  [page2_parser] Done.")
    return {
        "business_information":  business_information,
        "financial_information": financial_information,
    }
