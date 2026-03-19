import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, os.path.dirname(__file__))
from src.pdf_to_image      import convert_pdf_to_images
from src.ocr_engine        import run_ocr
from src.checkbox_detector import detect_checkboxes

# ── Drawing constants ─────────────────────────────────────────────────────────
TOKEN_COLOR   = (30,  144, 255)   # blue
CHECKED_COLOR = (0,   200,  50)   # green
UNCHECKED_COL = (220,  50,  50)   # red
RULER_COLOR   = (200, 200,   0)   # yellow
RULER_STEP    = 50                # draw a Y ruler line every N pixels
FONT_SIZE     = 14


def _font(size: int = FONT_SIZE) -> ImageFont.ImageFont:
    """Load a monospace font if available, fall back to default."""
    for name in ("cour.ttf", "DejaVuSansMono.ttf", "Courier New.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _draw_ruler(draw: ImageDraw.ImageDraw, img: Image.Image,
                font: ImageFont.ImageFont) -> None:
    """Draw horizontal Y-ruler lines every RULER_STEP pixels."""
    for y in range(0, img.height, RULER_STEP):
        draw.line([(0, y), (img.width, y)],
                  fill=(*RULER_COLOR, 70), width=1)
        draw.text((2, y + 1), str(y),
                  fill=(*RULER_COLOR, 180), font=font)


def draw_tokens(image: Image.Image, tokens: list[dict]) -> Image.Image:
    """Blue bounding boxes + text labels over the page image."""
    img  = image.copy().convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(over)
    font = _font()
    _draw_ruler(draw, img, font)

    for tok in tokens:
        x1, y1, x2, y2 = tok["x"], tok["y"], tok["x2"], tok["y2"]
        draw.rectangle([x1, y1, x2, y2],
                       fill=(*TOKEN_COLOR, 30),
                       outline=(*TOKEN_COLOR, 170), width=1)
        draw.text((x1, max(0, y1 - FONT_SIZE - 1)),
                  f'{tok["text"]}  cy={tok["cy"]} c={tok["conf"]:.2f}',
                  fill=(*TOKEN_COLOR, 210), font=font)

    return Image.alpha_composite(img, over).convert("RGB")


def draw_checkboxes(image: Image.Image, boxes: list[dict]) -> Image.Image:
    """Green (checked) / Red (unchecked) bounding boxes over the page image."""
    img  = image.copy().convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(over)
    font = _font()

    for box in boxes:
        x1, y1, x2, y2 = box["x"], box["y"], box["x2"], box["y2"]
        color = CHECKED_COLOR if box["checked"] else UNCHECKED_COL
        draw.rectangle([x1, y1, x2, y2],
                       fill=(*color, 55),
                       outline=(*color, 220), width=3)
        label = f'{"CHECK" if box["checked"] else "empty"}  cy={box["cy"]}  {box["style"]}'
        draw.text((x1, max(0, y1 - FONT_SIZE - 1)),
                  label, fill=(*color, 230), font=font)

    return Image.alpha_composite(img, over).convert("RGB")


def draw_combined(image: Image.Image,
                   tokens: list[dict],
                   boxes:  list[dict]) -> Image.Image:
    """Tokens (blue) + checkboxes (green/red) + Y ruler — the most useful view."""
    img  = image.copy().convert("RGBA")
    over = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(over)
    font = _font()
    _draw_ruler(draw, img, font)

    # Tokens
    for tok in tokens:
        x1, y1, x2, y2 = tok["x"], tok["y"], tok["x2"], tok["y2"]
        draw.rectangle([x1, y1, x2, y2],
                       fill=(*TOKEN_COLOR, 22),
                       outline=(*TOKEN_COLOR, 150), width=1)
        draw.text((x1, max(0, y1 - FONT_SIZE)),
                  f'{tok["text"]} ({tok["cy"]})',
                  fill=(*TOKEN_COLOR, 190), font=font)

    # Checkboxes drawn on top with thicker border
    for box in boxes:
        x1, y1, x2, y2 = box["x"], box["y"], box["x2"], box["y2"]
        color = CHECKED_COLOR if box["checked"] else UNCHECKED_COL
        draw.rectangle([x1, y1, x2, y2],
                       fill=(*color, 50),
                       outline=(*color, 255), width=3)
        draw.text((x2 + 4, y1),
                  f'{"CHECK" if box["checked"] else "empty"} cy={box["cy"]}',
                  fill=(*color, 240), font=font)

    return Image.alpha_composite(img, over).convert("RGB")


def save_report(tokens: list[dict], boxes: list[dict], path: str) -> None:
    """Write a plain-text report of all tokens and checkboxes with coordinates."""
    lines = [
        "=" * 70,
        "OCR TOKENS  (sorted top-to-bottom, left-to-right)",
        "=" * 70,
        f'{"cy":>5}  {"cx":>5}  {"conf":>5}  text',
        "-" * 70,
    ]
    for t in sorted(tokens, key=lambda t: (t["cy"], t["cx"])):
        lines.append(f'{t["cy"]:>5}  {t["cx"]:>5}  {t["conf"]:>5.2f}  {t["text"]}')

    lines += [
        "",
        "=" * 70,
        "CHECKBOXES  (sorted top-to-bottom, left-to-right)",
        "=" * 70,
        f'{"cy":>5}  {"cx":>5}  {"checked":>8}  {"style":>8}',
        "-" * 70,
    ]
    for b in sorted(boxes, key=lambda b: (b["cy"], b["cx"])):
        lines.append(
            f'{b["cy"]:>5}  {b["cx"]:>5}  {str(b["checked"]):>8}  {b["style"]:>8}'
        )

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"  [visualizer] Report saved → {path}")


def visualize_page(images: list, page_num: int, out_dir: str) -> None:
    
    os.makedirs(out_dir, exist_ok=True)
    idx = page_num - 1

    if idx >= len(images):
        print(f"  ERROR: only {len(images)} page(s) available, requested page {page_num}.")
        return

    print(f"\n[visualizer] Processing page {page_num}…")
    img    = images[idx]
    tokens = run_ocr(img, page=idx)
    boxes  = detect_checkboxes(img, page=idx, tokens=tokens)

    prefix = os.path.join(out_dir, f"debug_page_{page_num}")

    img.save(f"{prefix}_original.png")
    print(f"  Saved: {prefix}_original.png")

    draw_tokens(img, tokens).save(f"{prefix}_tokens.png")
    print(f"  Saved: {prefix}_tokens.png")

    draw_checkboxes(img, boxes).save(f"{prefix}_checkboxes.png")
    print(f"  Saved: {prefix}_checkboxes.png")

    draw_combined(img, tokens, boxes).save(f"{prefix}_combined.png")
    print(f"  Saved: {prefix}_combined.png  ← open this one")

    save_report(tokens, boxes, f"{prefix}_report.txt")

    checked_count = sum(b["checked"] for b in boxes)
    print(f"  Summary: {len(tokens)} tokens | "
          f"{len(boxes)} checkboxes ({checked_count} checked, "
          f"{len(boxes) - checked_count} unchecked)")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Visualize EasyOCR tokens and checkbox detections on a CQ PDF page."
    )
    ap.add_argument("--pdf",       required=True,
                    help="Path to the PDF file")
    ap.add_argument("--page",      type=int, default=3,
                    help="Page number to visualize, 1-based (default: 3)")
    ap.add_argument("--out",       default="temp_images",
                    help="Output directory for debug images (default: temp_images/)")
    ap.add_argument("--all-pages", action="store_true",
                    help="Visualize all pages")
    args = ap.parse_args()

    if not os.path.isfile(args.pdf):
        print(f"ERROR: PDF not found: {args.pdf}")
        sys.exit(1)

    # ── Load PDF once — not once per page ─────────────────────────────────────
    print(f"Loading PDF: {args.pdf}")
    images = convert_pdf_to_images(args.pdf, dpi=300)
    print(f"  {len(images)} page(s) loaded.\n")

    if args.all_pages:
        for i in range(len(images)):
            visualize_page(images, i + 1, args.out)
    else:
        visualize_page(images, args.page, args.out)

    print(f"\nDone. Debug images saved to: {args.out}/")


if __name__ == "__main__":
    main()