
"""
Usage:
    python main.py                                    # auto-finds PDF in data/
    python main.py --pdf path/to/form.pdf             # specific PDF
    python main.py --pdf form.pdf --out result.json   # custom output path
The pipeline auto-detects PDF type:
  Digital PDF  → PyMuPDF (zero noise, perfect text)
  Scanned PDF  → EasyOCR (image-based extraction)
  Both modes   → pixel-based checkbox detection
"""
import argparse
import os
import sys
import time
import glob
sys.path.insert(0, os.path.dirname(__file__))
from src.pdf_to_image      import convert_pdf_to_images
from src.pymupdf_engine    import extract_all_pages, is_digital_pdf
from src.ocr_engine        import run_ocr
from src.checkbox_detector import detect_checkboxes
from src.page1_parser      import parse_page1
from src.page2_parser      import parse_page2
from src.page3_parser      import parse_page3
from src.page4_parser      import parse_page4
from src.utils             import save_json

def find_pdf() -> str:
    """Auto-find a PDF in the data/ folder if none specified."""
    pdfs = glob.glob("data/*.pdf") + glob.glob("*.pdf")
    if not pdfs:
        print("ERROR: No PDF found. Place a PDF in the data/ folder or use --pdf path.")
        sys.exit(1)
    if len(pdfs) > 1:
        print(f"  Multiple PDFs found, using: {pdfs[0]}")
    return pdfs[0]

def run_pipeline(pdf_path: str,
                 output_path: str = "output/result.json",
                 save_debug_images: bool = False) -> dict:
    t0 = time.time()
    print(f"\n{'='*60}")
    print(f"  CQ INGESTION PIPELINE")
    print(f"  PDF    : {pdf_path}")
    print(f"  Output : {output_path}")
    print(f"{'='*60}\n")
    # ── Step 1: Convert PDF to images (always — needed for checkboxes) ─────────
    print("[1/4] Converting PDF to images (300 DPI)…")
    images = convert_pdf_to_images(pdf_path, dpi=300)
    if save_debug_images:
        img_dir = "temp_images"
        os.makedirs(img_dir, exist_ok=True)
        for i, img in enumerate(images):
            img.save(os.path.join(img_dir, f"page_{i+1}.png"))
        print(f"  Debug images saved → {img_dir}/")
    # ── Step 2: Auto-detect PDF type and extract text ──────────────────────────
    print("\n[2/4] Detecting PDF type and extracting text…")
    digital = is_digital_pdf(pdf_path)
    if digital:
        print("  Mode: HYBRID  (PyMuPDF text + pixel checkboxes)")
        all_text_tokens = extract_all_pages(pdf_path)
    else:
        print("  Mode: OCR-ONLY  (EasyOCR text + pixel checkboxes)")
        all_text_tokens = []
        for i, img in enumerate(images):
            all_text_tokens.append(run_ocr(img, page=i))
    # ── Step 3: Checkbox detection — always pixel-based ───────────────────────
    print("\n  Detecting checkboxes…")
    all_boxes = []
    for i, (img, tokens) in enumerate(zip(images, all_text_tokens)):
        all_boxes.append(detect_checkboxes(img, page=i, tokens=tokens))
    # ── Step 4: Parse ──────────────────────────────────────────────────────────
    print("\n[3/4] Parsing pages…")
    result = {}
    for fn, idx in [(parse_page1,0),(parse_page2,1),(parse_page3,2),(parse_page4,3)]:
        if idx < len(all_text_tokens):
            result.update(fn(all_text_tokens[idx], all_boxes[idx]))
    # ── Step 5: Save ───────────────────────────────────────────────────────────
    print("\n[4/4] Saving JSON…")
    save_json(result, output_path)
    elapsed = round(time.time() - t0, 2)
    print(f"\n{'='*60}")
    print(f"  DONE in {elapsed}s  →  {output_path}")
    print(f"{'='*60}")
    _print_summary(result)
    return result

def _print_summary(result: dict) -> None:
    gi   = result.get("general_information", {})
    refs = result.get("references", {})
    bi   = result.get("business_information", {})
    print(f"""
  Company  : {gi.get('company_name',    'N/A')}
  Contact  : {gi.get('primary_contact', 'N/A')}
  Phone    : {gi.get('phone',           'N/A')}
  Biz type : {', '.join(gi.get('type_of_business', []))}
  Owners   : {len(result.get('owners', []))}
  Bonded   : {bi.get('currently_bonded', 'N/A')}  ({bi.get('surety_name', '')})
  Projects : {len(result.get('projects', []))}
  Sub-refs : {len(refs.get('major_subcontractors', []))}
  OA-refs  : {len(refs.get('owners_and_architects', []))}
  Suppliers: {len(refs.get('suppliers', []))}
""")

def main():
    ap = argparse.ArgumentParser(description="CQ Ingestion Pipeline")
    ap.add_argument("--pdf",          default=None,
                    help="Path to PDF (optional — auto-finds PDF in data/ if omitted)")
    ap.add_argument("--out",          default="output/result.json",
                    help="Output JSON path (default: output/result.json)")
    ap.add_argument("--debug-images", action="store_true",
                    help="Save 300 DPI page images to temp_images/")
    args = ap.parse_args()
    pdf_path = args.pdf if args.pdf else find_pdf()
    if not os.path.isfile(pdf_path):
        print(f"ERROR: PDF not found: {pdf_path}")
        sys.exit(1)
    run_pipeline(pdf_path, args.out, args.debug_images)

if __name__ == "__main__":
    main()
