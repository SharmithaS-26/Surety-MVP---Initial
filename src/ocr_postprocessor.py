"""
src/ocr_postprocessor.py
────────────────────────
Post-processes the raw extraction dict produced by the page parsers
when the SCANNED PDF path (EasyOCR) was used.

USAGE (in main.py — already done):
    from src.ocr_postprocessor import clean_scanned_result
    if not is_digital:
        result = clean_scanned_result(result)

VERIFIED FIXES (tested against actual result_scanned.json):
  ✓ SSOMM  → 50MM    ✓ S1OMM  → 10MM    ✓ 52.SMM → 52.5MM
  ✓ Bean@OTCPAc.om  → Bean@OTCPA.com
  ✓ Bean@OTCPAcom   → Bean@OTCPA.com
  ✓ 1 NDale MabryHWY → 1 N Dale Mabry HWY
  ✓ Tampa; Florida  → Tampa, Florida
  ✓ Jordan Belfort VP → Jordan Belfort, VP
  ✓ "Fixed assets,AR" → "Fixed assets, AR"

HONEST LIMITATIONS (cannot be fixed at post-processing stage):
  ~ 520MM stays 520MM  — EasyOCR read $ as digit '5', indistinguishable
  ~ ZEMM  stays EMM    — Z decoded to nothing, E≠7 — unfixable without context
  ~ company_name, primary_contact, owners, type_of_business: never extracted
    by EasyOCR on page 1 — requires page1_parser fix
  ~ geographic_territory: page2_parser missed it on scanned path
  ~ Yes/No questionnaire nulls: checkbox_detector not firing on scanned pages
  ~ tax_basis/fin_stmt/fin_level []: same checkbox issue
  ~ OCR typos: "Mechancal", "Dintworks", "IimTracks" — character-level noise,
    unfixable without a dictionary or fuzzy matching
"""

import re


# ═══════════════════════════════════════════════════════════
#  ATOMIC CLEANERS
# ═══════════════════════════════════════════════════════════

_LEADING_NOISE  = re.compile(r'^[\s.;:,|_\[\]!]*')
_TRAILING_NOISE = re.compile(r'[\s_.,;:|!\]]+$')

def _strip(text: str) -> str:
    if not text:
        return text
    return _TRAILING_NOISE.sub('', _LEADING_NOISE.sub('', text)).strip()


def _fix_dollar(text: str) -> str:
    """
    Fix EasyOCR misreads on dollar amounts.
    Strategy: O/o→0 everywhere, strip exactly ONE leading S/Z/$ (the $ sign),
    then convert any remaining S→5 and re-exposed leading S→5.

    Examples:
        SSOMM  → 50MM   (strip S, S→5, O→0)
        S1OMM  → 10MM   (strip S, O→0)
        52.SMM → 52.5MM (no leading strip needed, embedded S→5)
        520MM  → 520MM  (EasyOCR read $ as digit 5 — can't distinguish)
        ZEMM   → EMM    (Z stripped, E≠7 — unrecoverable)
        500,000→ 500,000 (already correct)
    """
    if not text:
        return text
    text = text.strip()
    text = re.sub(r'[Oo]', '0', text)                              # O/o → 0
    text = re.sub(r'^[SsZz$]', '', text)                           # strip one leading S/Z/$
    text = re.sub(r'(?<=[0-9.])[Ss](?=[0-9MmKkBb.])', '5', text)  # embedded S → 5
    text = re.sub(r'^[Ss](?=[0-9])', '5', text)                    # re-exposed leading S → 5
    return text


_KNOWN_TLDS = {'com', 'net', 'org', 'gov', 'edu', 'io', 'co', 'us', 'biz', 'info'}

def _fix_email(text: str) -> str:
    """
    Fix OCR email noise:
    - "Bean@OTCPAc.om"  → "Bean@OTCPA.com"  (dot in wrong position)
    - "Bean@OTCPAcom"   → "Bean@OTCPA.com"  (missing dot before TLD)
    - "user@domain com" → "user@domain.com"  (space before TLD)
    """
    if not text or '@' not in text:
        return text
    text = _strip(text)
    # Space before TLD
    text = re.sub(r'(@[A-Za-z0-9._-]+)\s+([A-Za-z]{2,6})$', r'\1.\2', text)
    # Misplaced dot: "@OTCPAc.om" → "@OTCPA.com"
    def _fix_misplaced(m):
        domain = m.group(1)
        tld    = m.group(2)
        candidate = domain[-1].lower() + tld.lower()
        if candidate in _KNOWN_TLDS:
            return domain[:-1] + '.' + candidate
        return domain + '.' + tld
    text = re.sub(
        r'(@[A-Za-z0-9_-]+[A-Za-z])\.([A-Za-z]{1,4})$',
        _fix_misplaced, text
    )
    # Missing dot: "@OTCPAcom" → "@OTCPA.com"
    if '@' in text and '.' not in text.split('@')[1]:
        local, domain_part = text.split('@', 1)
        for tld in sorted(_KNOWN_TLDS, key=len, reverse=True):
            if domain_part.lower().endswith(tld):
                text = local + '@' + domain_part[:-len(tld)] + '.' + tld
                break
    return text


def _fix_address(text: str) -> str:
    """
    Fix address OCR issues:
    - Semicolons → commas:   "Tampa; Florida" → "Tampa, Florida"
    - Underscores → spaces:  "Mabry_HWY" → "Mabry HWY"
    - Missing spaces:        "NDale" → "N Dale", "MabryHWY" → "Mabry HWY"
    """
    if not text:
        return text
    text = text.replace(';', ',').replace('_', ' ')
    text = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', text)   # NDale → N Dale
    text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)          # MabryHWY → Mabry HWY
    return re.sub(r'  +', ' ', text).strip()


def _fix_comma_spacing(text: str) -> str:
    """'Fixed assets,AR' → 'Fixed assets, AR'"""
    if not text:
        return text
    return re.sub(r',(?=[A-Za-z])', ', ', text)


def _fix_title_suffix(text: str) -> str:
    """'Jordan Belfort VP' → 'Jordan Belfort, VP'"""
    if not text:
        return text
    return re.sub(r'\s+(VP|CEO|CFO|CPA|MD|Jr|Sr|II|III)\.?$', r', \1', text)


_LABEL_PREFIXES = [
    "company name", "companyname", "address:", "phone",
    "primary contact", "type of business", "date business",
    "fed tax", "naics", "corporate officers",
]

def _looks_like_label(text: str) -> bool:
    t = text.lower().strip()
    return any(t.startswith(lp) for lp in _LABEL_PREFIXES)


# ═══════════════════════════════════════════════════════════
#  SECTION CLEANERS
# ═══════════════════════════════════════════════════════════

def _clean_general_information(gi: dict) -> dict:
    gi["company_name"]    = _strip(gi.get("company_name", ""))
    gi["address"]         = _fix_address(_strip(gi.get("address", "")))
    gi["phone"]           = _strip(gi.get("phone", ""))
    gi["primary_contact"] = _strip(gi.get("primary_contact", ""))
    gi["email"]           = _fix_email(gi.get("email", ""))
    gi["fed_tax_id"]      = _strip(gi.get("fed_tax_id", ""))
    return gi


def _clean_owners(owners: list) -> list:
    cleaned = []
    for o in owners:
        name = _strip(o.get("name", ""))
        if _looks_like_label(name):
            continue
        if any(kw in name.lower() for kw in
               ["company name", "companyname", "address:", "phone"]):
            continue
        o["name"]           = name
        o["title"]          = _strip(o.get("title", ""))
        o["ownership_pct"]  = _strip(o.get("ownership_pct", ""))
        o["address"]        = _fix_address(_strip(o.get("address", "")))
        o["city_state_zip"] = _strip(o.get("city_state_zip", ""))
        o["dob"]            = _strip(o.get("dob", ""))
        o["ssn"]            = _strip(o.get("ssn", ""))
        sp = o.get("spouse", {})
        if sp:
            o["spouse"] = {
                "name": _strip(sp.get("name", "")),
                "dob":  _strip(sp.get("dob", "")),
                "ssn":  _strip(sp.get("ssn", "")),
            }
        if o["name"]:
            cleaned.append(o)
    return cleaned


def _clean_business_information(bi: dict) -> dict:
    bi["trades_self_performed"] = _strip(bi.get("trades_self_performed", ""))
    bi["trades_subcontracted"]  = _strip(bi.get("trades_subcontracted", ""))
    bi["geographic_territory"]  = _strip(bi.get("geographic_territory", ""))
    bi["surety_name"]           = _strip(bi.get("surety_name", ""))

    # Percentages — extract first valid integer 0-100
    for key in ["work_acquired_bid_pct", "work_acquired_negotiated_pct",
                "work_public_pct", "work_private_pct"]:
        val = bi.get(key, "")
        if val:
            m = re.search(r'\b(\d{1,3})\b', val)
            if m and 0 <= int(m.group(1)) <= 100:
                bi[key] = m.group(1)

    # Dollar amounts
    for key in ["largest_cost_to_complete", "desired_bond_single",
                "desired_bond_aggregate"]:
        bi[key] = _fix_dollar(_strip(bi.get(key, "")))

    return bi


def _clean_financial_information(fi: dict) -> dict:
    fi["cpa_firm"]    = _strip(fi.get("cpa_firm", ""))
    fi["cpa_address"] = _fix_address(fi.get("cpa_address", "").replace(';', ','))
    fi["cpa_contact"] = _strip(fi.get("cpa_contact", ""))
    fi["cpa_email"]   = _fix_email(fi.get("cpa_email", ""))
    return fi


def _clean_banking(bk: dict) -> dict:
    bk["bank_name"]    = _strip(bk.get("bank_name", ""))
    bk["contact_name"] = _fix_title_suffix(_strip(bk.get("contact_name", "")))
    bk["bank_address"] = _fix_address(_strip(bk.get("bank_address", "")))
    bk["bank_phone"]   = _strip(bk.get("bank_phone", ""))
    bk["bank_email"]   = _fix_email(bk.get("bank_email", ""))
    bk["how_secured"]  = _fix_comma_spacing(_strip(bk.get("how_secured", "")))
    bk["total_line_of_credit"] = _fix_dollar(
        _strip(bk.get("total_line_of_credit", "")))
    return bk


def _clean_projects(projects: list) -> list:
    for p in projects:
        p["project_name"]         = _strip(p.get("project_name", ""))
        p["final_contract_price"] = _fix_dollar(
            _strip(p.get("final_contract_price", "")))
        p["gross_profit"]         = _fix_dollar(_strip(p.get("gross_profit", "")))
        p["for_whom_contact"]     = _strip(p.get("for_whom_contact", ""))
        # Clear ghost rows where only noise was extracted
        if p["final_contract_price"] in ("", "5", "S", "$"):
            p["final_contract_price"] = ""
        if p["gross_profit"] in ("", "5", "S", "$"):
            p["gross_profit"] = ""
    return projects


def _clean_references(refs: dict) -> dict:
    for section in ["major_subcontractors", "owners_and_architects", "suppliers"]:
        cleaned = []
        for entry in refs.get(section, []):
            company = _strip(entry.get("company", ""))
            contact = _strip(entry.get("contact", ""))
            phone   = _strip(entry.get("phone", ""))
            # Strip leading OCR bracket/pipe noise before capital letter
            company = re.sub(r'^[\[|I]+(?=[A-Z])', '', company).strip()
            contact = re.sub(r'^[I\[|]+(?=[A-Z])', '', contact).strip()
            if company or contact:
                cleaned.append({
                    "company": company,
                    "phone":   phone,
                    "contact": contact,
                })
        refs[section] = cleaned
    return refs


# ═══════════════════════════════════════════════════════════
#  MASTER CLEANER
# ═══════════════════════════════════════════════════════════

def clean_scanned_result(result: dict) -> dict:
    """
    Apply all OCR post-processing fixes to the raw extraction result.
    Call this only when is_digital_pdf() returned False.
    """
    print("  [ocr_postprocessor] Cleaning scanned extraction result...")

    if "general_information" in result:
        result["general_information"] = _clean_general_information(
            result["general_information"])

    if "owners" in result:
        result["owners"] = _clean_owners(result["owners"])

    if "business_information" in result:
        result["business_information"] = _clean_business_information(
            result["business_information"])

    if "financial_information" in result:
        result["financial_information"] = _clean_financial_information(
            result["financial_information"])

    if "banking" in result:
        result["banking"] = _clean_banking(result["banking"])

    if "projects" in result:
        result["projects"] = _clean_projects(result["projects"])

    if "references" in result:
        result["references"] = _clean_references(result["references"])

    print("  [ocr_postprocessor] Done.")
    return result