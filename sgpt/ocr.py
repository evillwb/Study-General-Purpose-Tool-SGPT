"""OCR for scanned PDFs and photos of exam pages.

Uses RapidOCR (pip install rapidocr onnxruntime), which runs offline with its built-in models
and needs no other software. If it is not installed but Tesseract is, PyMuPDF's Tesseract
OCR is used instead.
"""

from __future__ import annotations

import logging
import re
import threading

_engine = None
_lock = threading.Lock()


def _rapidocr():
    global _engine
    with _lock:
        if _engine is None:
            from rapidocr import RapidOCR

            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            _engine = RapidOCR()
            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
        return _engine


def available() -> str | None:
    """Name of the OCR engine that will be used, or None."""
    try:
        import onnxruntime  # noqa: F401
        import rapidocr  # noqa: F401

        return "rapidocr"
    except ImportError:
        pass
    try:
        import pymupdf

        if pymupdf.get_tessdata():
            return "tesseract"
    except Exception:  # get_tessdata raises when Tesseract is not installed
        pass
    return None


def _lines_from_boxes(boxes, texts) -> str:
    """Rebuild reading order: group text boxes into lines from top to bottom, left to right."""
    items = []
    for box, text in zip(boxes, texts):
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), max(ys), min(xs), text))
    items.sort(key=lambda i: (i[0], i[2]))
    lines: list[list[tuple]] = []
    for item in items:
        top, bottom = item[0], item[1]
        if lines:
            last = lines[-1]
            l_top = min(i[0] for i in last)
            l_bottom = max(i[1] for i in last)
            overlap = min(bottom, l_bottom) - max(top, l_top)
            if overlap > 0.5 * min(bottom - top, l_bottom - l_top):
                last.append(item)
                continue
        lines.append([item])
    return "\n".join(" ".join(i[3] for i in sorted(line, key=lambda i: i[2])) for line in lines)


def tidy(text: str) -> str:
    """Undo common OCR spacing slips: "2 0" -> "20", "2 ." -> "2." at the start of a line."""
    text = re.sub(r"(?<=\d) (?=\d)", "", text)
    return re.sub(r"(?m)^(\s*\d{1,2}) ([.)．、])", r"\1\2", text)


def ocr_boxes(data: bytes) -> list[tuple[list, str]]:
    """OCR an image and return [(box corner points in pixels, text), ...] (RapidOCR only)."""
    result = _rapidocr()(data)
    if result is None or result.boxes is None or result.txts is None:
        return []
    return [(box, text) for box, text in zip(result.boxes.tolist(), result.txts) if text.strip()]


def ocr_image(data: bytes) -> str:
    """OCR a PNG/JPEG image given as bytes."""
    engine = available()
    if engine == "rapidocr":
        result = _rapidocr()(data)
        if result is None or result.boxes is None or result.txts is None:
            return ""
        return tidy(_lines_from_boxes(result.boxes.tolist(), result.txts))
    if engine == "tesseract":
        import pymupdf

        with pymupdf.open(stream=data) as img_doc:
            pdf = pymupdf.open("pdf", img_doc.convert_to_pdf())
        page = pdf[0]
        return tidy(page.get_text(textpage=page.get_textpage_ocr(full=True, dpi=300)))
    raise RuntimeError("OCR is not installed. Run: pip install rapidocr onnxruntime")


def ocr_pdf_page(page, dpi: int = 200) -> str:
    """OCR one PyMuPDF page."""
    if available() == "tesseract":
        return tidy(page.get_text(textpage=page.get_textpage_ocr(full=True, dpi=300), sort=True))
    return ocr_image(page.get_pixmap(dpi=dpi).tobytes("png"))


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


def ocr_document(name: str, data: bytes, *, force: bool = False, step=None,
                 should_stop=None) -> list[dict]:
    """OCR a PDF or image. Returns [{"page": 1, "text": "...", "method": "ocr" | "text"}].

    PDF pages that already have selectable text keep it, unless force=True.
    """
    import pymupdf

    if not available():
        raise RuntimeError("OCR is not installed. Run: pip install rapidocr onnxruntime")
    suffix = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if suffix in IMAGE_SUFFIXES:
        if step:
            step(1, 1)
        return [{"page": 1, "text": ocr_image(data), "method": "ocr"}]
    if suffix != ".pdf":
        raise RuntimeError(f"{name}: use a PDF or an image (PNG, JPG…)")
    pages = []
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        for i, page in enumerate(doc):
            if should_stop and should_stop():
                raise InterruptedError()
            if step:
                step(i + 1, len(doc))
            text = page.get_text("text", sort=True)
            if force or len(text.strip()) < 25:
                pages.append({"page": i + 1, "text": ocr_pdf_page(page), "method": "ocr"})
            else:
                pages.append({"page": i + 1, "text": text.strip(), "method": "text"})
    return pages


def main(argv: list[str] | None = None) -> int:
    """python -m sgpt.ocr scan.pdf photo.jpg [-o result.txt] [--force]"""
    import argparse
    import sys
    from pathlib import Path

    p = argparse.ArgumentParser(prog="sgpt.ocr",
                                description="Extract text from scanned PDFs and photos (offline OCR).")
    p.add_argument("files", nargs="+", help="PDF or image files")
    p.add_argument("-o", "--output", help="save the text to this file (default: print it)")
    p.add_argument("--force", action="store_true",
                   help="OCR every page, even pages that already have selectable text")
    args = p.parse_args(argv)
    chunks = []
    for name in args.files:
        path = Path(name)
        try:
            pages = ocr_document(path.name, path.read_bytes(), force=args.force,
                                 step=lambda i, n: print(f"{path.name}: page {i}/{n}", file=sys.stderr))
        except (OSError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        for page in pages:
            header = f"===== {path.name} — page {page['page']} =====" if len(args.files) > 1 or len(pages) > 1 else ""
            chunks.append(f"{header}\n{page['text']}".strip())
    text = "\n\n".join(chunks) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Saved to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
