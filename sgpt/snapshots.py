"""Pictures of past-paper questions, cut from the original pages.

A picture keeps diagrams, graphs, tables and maths symbols exactly as printed, which text
extraction can lose or garble. Each question is cropped from where its number appears to
where the next question starts (across pages if needed). Scanned pages are located with
OCR boxes.
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

ZOOM = 2.0           # render scale (2 = 144 dpi): sharp enough to read small symbols
MAX_PAGES = 3        # a question spanning more pages is cut after this many
TOP, BOTTOM = 0.06, 0.06  # page margins treated as running header/footer on continued pages
OCR_DPI = 150

_NUM = r"(?:question|q\.?|soalan|第)?\s*{n}\s*(?:题|題)?\s*(?:[.)．、:：]|\s|$)"
_WS = re.compile(r"\s+")


def _rows(items: list[tuple[float, float, float, float, str]]) -> list[tuple[float, float, str]]:
    """Group text pieces (x0, y0, x1, y1, text) into visual lines: (top, bottom, text)."""
    rows: list[list] = []
    for x0, y0, x1, y1, text in sorted(items, key=lambda i: (i[1] + i[3]) / 2):
        mid, height = (y0 + y1) / 2, max(y1 - y0, 1)
        if rows and abs(mid - rows[-1][3]) < height * 0.5:
            rows[-1][0] = min(rows[-1][0], y0)
            rows[-1][1] = max(rows[-1][1], y1)
            rows[-1][2].append((x0, text))
        else:
            rows.append([y0, y1, [(x0, text)], mid])
    return [(top, bottom, " ".join(t for _, t in sorted(parts))) for top, bottom, parts, _ in rows]


def _page_items(page, cache: dict) -> list:
    """Text pieces with positions, from the text layer or (for scans) OCR."""
    words = page.get_text("words")
    if len("".join(w[4] for w in words)) >= 25 or not page.get_images():
        return [(w[0], w[1], w[2], w[3], w[4]) for w in words]
    key = f"p{page.number}"
    if key not in cache:
        from . import ocr

        scale = 72 / OCR_DPI
        boxes = ocr.ocr_boxes(page.get_pixmap(dpi=OCR_DPI).tobytes("png"))
        cache[key] = [(min(p[0] for p in box) * scale, min(p[1] for p in box) * scale,
                       max(p[0] for p in box) * scale, max(p[1] for p in box) * scale, ocr.tidy(text))
                      for box, text in boxes]
    return cache[key]


def _start(rows, number: str, text: str, after: float) -> float | None:
    """Top of the line where question `number` starts, below `after`."""
    pattern = re.compile(r"^\s*" + _NUM.format(n=re.escape(number)), re.IGNORECASE)
    first = _WS.sub("", (text.strip().splitlines() or [""])[0])[:8].lower()
    fallback = None
    for top, _, line in rows:
        if top < after - 1 or not pattern.match(line):
            continue
        if first and first in _WS.sub("", line).lower():
            return top
        fallback = top if fallback is None else fallback
    return fallback


def locate(doc, questions: list[dict], cache: dict | None = None) -> list[tuple[int, float] | None]:
    """(page index, top y) where each question starts, in order; None if not found."""
    cache = {} if cache is None else cache
    rows_by_page: dict[int, list] = {}
    found, last = [], (-1, 0.0)
    for q in questions:
        index = (q.get("page") or 0) - 1
        if not 0 <= index < len(doc):
            found.append(None)
            continue
        if index not in rows_by_page:
            rows_by_page[index] = _rows(_page_items(doc[index], cache))
        after = last[1] if last[0] == index else 0.0
        top = _start(rows_by_page[index], str(q.get("number") or ""), q.get("text") or "", after)
        if top is None:
            found.append(None)
            continue
        found.append((index, top))
        last = (index, top)
    return found


def _segments(doc, start: tuple[int, float], end: tuple[int, float] | None):
    """Clip rectangles, page by page, from start to just before end (or the page bottom)."""
    import pymupdf

    first, y = start
    last = min(end[0] if end else first, first + MAX_PAGES - 1)
    out = []
    for n in range(first, last + 1):
        rect = doc[n].rect
        top = max(y - 4, 0) if n == first else rect.height * TOP
        bottom = end[1] - 3 if end and n == end[0] else rect.height * (1 - BOTTOM)
        if bottom - top > 8:
            out.append((n, pymupdf.Rect(0, top, rect.width, bottom)))
    return out


def _trim(png: bytes, pad: int = 12) -> bytes:
    """Cut the white border around the content."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return png
    image = Image.open(io.BytesIO(png)).convert("RGB")
    box = ImageOps.invert(image.convert("L")).point(lambda v: 255 if v > 40 else 0).getbbox()
    if not box:
        return png
    box = (max(box[0] - pad, 0), max(box[1] - pad, 0),
           min(box[2] + pad, image.width), min(box[3] + pad, image.height))
    buffer = io.BytesIO()
    image.crop(box).save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def picture(doc, segments) -> bytes | None:
    """One PNG with the clipped page pieces stacked top to bottom."""
    import pymupdf

    if not segments:
        return None
    width = max(clip.width for _, clip in segments)
    height = sum(clip.height for _, clip in segments)
    out = pymupdf.open()
    page = out.new_page(width=width, height=height)
    y = 0.0
    for n, clip in segments:
        page.show_pdf_page(pymupdf.Rect(0, y, clip.width, y + clip.height), doc, n, clip=clip)
        y += clip.height
    png = page.get_pixmap(matrix=pymupdf.Matrix(ZOOM, ZOOM)).tobytes("png")
    out.close()
    return _trim(png)


def snapshot_questions(pdf: Path, questions: list[dict], out_dir: Path, prefix: str,
                       cache: dict | None = None) -> int:
    """Save a picture of each question as out_dir/<prefix><id>.png and set q["image"].

    `questions` are one paper's questions in order (with "number", "text", "page", "id").
    Returns how many pictures were made.
    """
    import pymupdf

    from .pdf_extract import _cache_file

    made = 0
    out_dir.mkdir(parents=True, exist_ok=True)
    box_file = _cache_file(pdf).with_name(_cache_file(pdf).stem + "-boxes.json")
    if cache is None:
        try:
            cache = json.loads(box_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
    before = len(cache)
    with pymupdf.open(pdf) as doc:
        starts = locate(doc, questions, cache)
        for i, (q, start) in enumerate(zip(questions, starts)):
            if start is None:
                continue
            end = next((s for s in starts[i + 1:] if s is not None), None)
            try:
                png = picture(doc, _segments(doc, start, end))
            except (RuntimeError, ValueError):
                png = None
            if png:
                name = f"{prefix}{re.sub(r'[^A-Za-z0-9_-]', '_', q['id'])}.png"
                (out_dir / name).write_bytes(png)
                q["image"] = name
                made += 1
    if len(cache) > before:  # OCR'd some scanned pages: keep the positions for next time
        try:
            box_file.parent.mkdir(exist_ok=True)
            box_file.write_text(json.dumps(cache), encoding="utf-8")
        except OSError:
            pass
    return made
