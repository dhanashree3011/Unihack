"""
ocr.py
-------
Fallback text extraction for scanned manuals/spec sheets. PyMuPDF
rasterizes each page to an image, light preprocessing improves contrast,
then Tesseract reads it.

Resilience note: a missing/misconfigured Tesseract install must NEVER
take down a whole batch run over one scanned PDF. Every public function
here catches TesseractNotFoundError (and, defensively, any other OCR
failure) and returns "" instead of raising.
"""
import io
import os
import shutil
import sys
import pymupdf
import pytesseract
from pytesseract import TesseractNotFoundError
from PIL import Image, ImageOps, ImageFilter

_warned = False


def _locate_tesseract():
    env_override = os.environ.get("TESSERACT_CMD")
    if env_override and os.path.exists(env_override):
        pytesseract.pytesseract.tesseract_cmd = env_override
        return
    if shutil.which("tesseract"):
        return
    if sys.platform.startswith("win"):
        for candidate in (
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        ):
            if os.path.exists(candidate):
                pytesseract.pytesseract.tesseract_cmd = candidate
                return


_locate_tesseract()


def is_available() -> bool:
    try:
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


def _warn_once():
    global _warned
    if not _warned:
        print(
            "[ocr.py] Tesseract OCR was not found - scanned/image-only PDFs will be "
            "skipped (their text-based pages still extract normally). Install it from "
            "https://github.com/UB-Mannheim/tesseract/wiki (Windows) or your OS package "
            "manager, or set the TESSERACT_CMD environment variable to its full path."
        )
        _warned = True


def _preprocess(img: Image.Image) -> Image.Image:
    img = img.convert("L")
    img = ImageOps.autocontrast(img)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def ocr_pdf_bytes(pdf_bytes: bytes, dpi: int = 300, max_pages: int = 15) -> str:
    """Returns "" (never raises) if Tesseract isn't available or OCR fails."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        zoom = dpi / 72
        matrix = pymupdf.Matrix(zoom, zoom)
        texts = []
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            pix = page.get_pixmap(matrix=matrix)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img = _preprocess(img)
            texts.append(pytesseract.image_to_string(img))
        doc.close()
        return "\n".join(texts)
    except TesseractNotFoundError:
        _warn_once()
        return ""
    except Exception as e:
        print(f"[ocr.py] OCR failed on a PDF, skipping it: {e!r}")
        return ""


def ocr_image_bytes(image_bytes: bytes) -> str:
    """Returns "" (never raises) if Tesseract isn't available or OCR fails."""
    try:
        img = _preprocess(Image.open(io.BytesIO(image_bytes)))
        return pytesseract.image_to_string(img)
    except TesseractNotFoundError:
        _warn_once()
        return ""
    except Exception as e:
        print(f"[ocr.py] OCR failed on an image, skipping it: {e!r}")
        return ""