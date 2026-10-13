"""Rebuild scanned pages with their layout, so OCR output keeps the original look.

Each scanned page becomes a new PDF page of the same size: every line of text the OCR
found is written at the same place and size, and diagrams, graphs and photos (anything
on the page that isn't text) are cut out of the scan and placed where they were. Turning
that PDF into Word (with pdf2docx) gives an editable document laid out like the scan.
"""

from __future__ import annotations

import re
from pathlib import Path

DPI = 200
_CJK = re.compile(r"[　-ヿ㐀-鿿豈-﫿＀-￯]")


def _figures(png: bytes, boxes: list) -> list[tuple[int, int, int, int]]:
    """Pixel rectangles of non-text ink (diagrams, photos) on a page image."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return []
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if image is None:
        return []
    height, width = image.shape
    ink = (image < 170).astype(np.uint8)
    for box, _ in boxes:  # hide the text
        xs, ys = [int(p[0]) for p in box], [int(p[1]) for p in box]
        ink[max(min(ys) - 3, 0):max(ys) + 3, max(min(xs) - 3, 0):max(xs) + 3] = 0
    ink = cv2.dilate(ink, np.ones((25, 25), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(ink)
    figures = []
    for x, y, w, h, area in stats[1:count]:
        # Big enough to be a picture, and not a thin rule or underline.
        if w * h > width * height * 0.01 and w > 60 and h > 60:
            figures.append((int(x), int(y), int(x + w), int(y + h)))
    return figures


def _bounds(box) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in box], [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def _touches(box, rect, margin: float = 0) -> bool:
    x0, y0, x1, y1 = _bounds(box)
    return (x0 < rect[2] + margin and x1 > rect[0] - margin
            and y0 < rect[3] + margin and y1 > rect[1] - margin)


LABEL_GAP = 25  # pixels at DPI: short text this close to a diagram is one of its labels


def _with_labels(figures: list, boxes: list) -> list:
    """Grow each figure to take in its labels (A, B, C, axis values…): short pieces of text
    touching it or within LABEL_GAP of it, and longer text that overlaps it."""
    grown = []
    for rect in figures:
        rect = list(rect)
        for box, text in boxes:
            near = LABEL_GAP if len(text.strip()) <= 12 else 0
            if _touches(box, rect, near):
                x0, y0, x1, y1 = _bounds(box)
                rect = [min(rect[0], x0), min(rect[1], y0), max(rect[2], x1), max(rect[3], y1)]
        grown.append(tuple(int(v) for v in rect))
    return grown


def _sizes(heights: list[float]) -> list[float]:
    """Font size per line: lines close to the page's usual size get exactly that size, so
    body text doesn't wobble; headings and small print keep their own size."""
    if not heights:
        return []
    usual = sorted(heights)[len(heights) // 2]
    return [usual if abs(h - usual) <= usual * 0.3 else h for h in heights]


def rebuild_page(out_doc, src_page, png: bytes, boxes: list) -> None:
    """Add a page to out_doc that looks like src_page (a scan) but with real text."""
    import pymupdf

    rect = src_page.rect
    page = out_doc.new_page(width=rect.width, height=rect.height)
    scale = rect.width / pymupdf.Pixmap(png).width  # pixels -> points
    figures = _with_labels(_figures(png, boxes), boxes)
    for x0, y0, x1, y1 in figures:
        # The figure keeps its own labels: they are part of the picture.
        clip = pymupdf.Rect(x0 * scale, y0 * scale, x1 * scale, y1 * scale)
        crop = src_page.get_pixmap(dpi=DPI, clip=clip).tobytes("png")
        page.insert_image(clip, stream=crop)
    lines = [(_bounds(box), text) for box, text in boxes
             if text.strip() and not any(_touches(box, f) for f in figures)]
    sizes = _sizes([(b[3] - b[1]) * scale * 0.8 for b, _ in lines])
    # Pieces of one printed line (OCR often splits a line) share a baseline and size, so
    # Word sees one line of text.
    order = sorted(range(len(lines)), key=lambda i: (lines[i][0][1] + lines[i][0][3]) / 2)
    rows: list[list[int]] = []
    for i in order:
        mid = (lines[i][0][1] + lines[i][0][3]) / 2
        last = rows[-1] if rows else None
        if last and abs(mid - sum((lines[j][0][1] + lines[j][0][3]) / 2 for j in last) / len(last)) \
                < (lines[i][0][3] - lines[i][0][1]) * 0.5:
            last.append(i)
        else:
            rows.append([i])
    fonts = {}
    for row in rows:
        middle = sum((lines[j][0][1] + lines[j][0][3]) / 2 for j in row) / len(row) * scale
        row_size = max(sorted(sizes[j] for j in row)[len(row) // 2], 4)
        pieces: list[list] = []  # [x0, x1, text]: close pieces joined, columns kept apart
        for j in sorted(row, key=lambda j: lines[j][0][0]):
            (x0, y0, x1, y1), text = lines[j]
            if pieces and x0 - pieces[-1][1] < (y1 - y0) * 2:
                pieces[-1][1] = max(pieces[-1][1], x1)
                pieces[-1][2] += ("" if _CJK.search(pieces[-1][2][-1:] + text[:1]) else " ") + text
            else:
                pieces.append([x0, x1, text])
        for x0, x1, text in pieces:
            x0, x1 = x0 * scale, x1 * scale
            name = "china-s" if _CJK.search(text) else "helv"
            if name not in fonts:
                fonts[name] = pymupdf.Font(name)
            size = row_size
            width = fonts[name].text_length(text, size)
            if width > (x1 - x0) * 1.05 and width > 0:
                size = max(size * (x1 - x0) * 1.05 / width, 4)
            page.insert_text((x0, middle + row_size * 0.35), text, fontsize=size, fontname=name)


def layout_pdf(src: Path, out: Path, *, step=None, should_stop=None, min_chars: int = 25) -> Path:
    """A copy of src (PDF or image) where every scanned page is rebuilt with real text in
    the same layout. Pages that already have text are kept as they are."""
    import pymupdf

    from . import ocr

    if not ocr.available():
        raise RuntimeError("OCR is not installed: pip install rapidocr onnxruntime")
    if src.suffix.lower() == ".pdf":
        doc = pymupdf.open(src)
    else:
        with pymupdf.open(src) as img:
            doc = pymupdf.open("pdf", img.convert_to_pdf())
    out_doc = pymupdf.open()
    try:
        for page in doc:
            if should_stop and should_stop():
                raise InterruptedError()
            if step:
                step(page.number + 1, len(doc))
            if len(page.get_text().strip()) >= min_chars or not page.get_images():
                out_doc.insert_pdf(doc, from_page=page.number, to_page=page.number)
                continue
            png = page.get_pixmap(dpi=DPI).tobytes("png")
            boxes = [(box, ocr.tidy(text)) for box, text in ocr.ocr_boxes(png)]
            rebuild_page(out_doc, page, png, boxes)
        out_doc.save(out, garbage=3, deflate=True)
    finally:
        out_doc.close()
        doc.close()
    return out
