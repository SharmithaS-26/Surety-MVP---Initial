import fitz  # PyMuPDF
from PIL import Image
import io
import os


def convert_pdf_to_images(pdf_path: str, dpi: int = 300) -> list[Image.Image]:
    """
    Convert every page of a PDF to a PIL Image at the given DPI.

    Args:
        pdf_path: Path to the PDF file.
        dpi:      Resolution for rendering (300 recommended for OCR).

    Returns:
        List of PIL Images, one per page.
    """
    doc = fitz.open(pdf_path)
    images = []
    zoom = dpi / 72  # PyMuPDF default is 72 DPI
    mat = fitz.Matrix(zoom, zoom)

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
        images.append(img)
        print(f"  [pdf_to_image] Page {page_num + 1} → {img.size[0]}x{img.size[1]} px")

    doc.close()
    return images


def save_page_images(images: list[Image.Image], out_dir: str) -> list[str]:
    """Save PIL Images to disk and return their paths."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, img in enumerate(images):
        path = os.path.join(out_dir, f"page_{i + 1}.png")
        img.save(path)
        paths.append(path)
    return paths