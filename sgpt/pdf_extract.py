"""Extract text and a rough question structure from past-paper PDFs (with OCR for scans)."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Question:
    number: str
    text: str
    marks: int | None = None
    section: str = ""  # chapter/paper heading when numbering restarts, e.g. "Bab 3"
    page: int = 0      # page the question starts on (1-based)


@dataclass
class ExamPaper:
    path: Path
    title: str
    text: str
    page_count: int
    questions: list[Question] = field(default_factory=list)
    ocr_pages: int = 0  # pages that were read with OCR

    @property
    def total_marks(self) -> int | None:
        marks = [q.marks for q in self.questions if q.marks is not None]
        return sum(marks) if marks else None


# "Question 3", "Q3", "Q.3", Malay "Soalan 3", Chinese "第3题" / "第 3 題"
_QUESTION_WORD = re.compile(
    r"^\s*(?:question|q\.?|soalan|第)\s*(\d{1,2})(?!\d)\s*(?:题|題)?[.):：、．]?\s*(.*)$", re.IGNORECASE)
# "3." or "3)" followed by a space or a Chinese character, or Chinese-style "3．" / "3、"
_QUESTION_NUM = re.compile(r"^\s*(\d{1,2})(?:[.)]\s+|[.)](?=[\u3400-\u9fff])|\s*[．、])\s*(\S.*)$")
# "[5 marks]", "(5 marks)", "[5]", "(Total 12 marks)", "(5 markah)", "（5分）", "【5分】"
_MARKS = re.compile(
    r"[\[(（【]\s*(?:(?:total|jumlah)\s*(?:for\s*question\s*\d+\s*(?:is|=)?\s*)?:?\s*)?"
    r"(\d{1,3})\s*(?:marks?|markah|m|分)?\s*[\])）】]",
    re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(
    r"^\s*(?:page|halaman|第)?\s*\d{1,3}\s*(?:页|頁)?(?:\s*(?:of|/|daripada|共)\s*\d{1,3}\s*(?:页|頁)?)?\s*$",
    re.IGNORECASE)


# Lines that start a new chapter/paper inside a compiled file, where numbering restarts at 1.
_SECTION = re.compile(
    r"(?:\b(?:chapter|bab|unit|topic|topik|section|bahagian|paper|kertas|part|tingkatan|form|"
    r"year|tahun)\b|第\s*[\d一二三四五六七八九十百]+\s*[章课課单單元回]|\b(?:19|20)\d{2}\b)",
    re.IGNORECASE)
_PAGE_MARK = re.compile(r"^\x01(\d+)$")

MIN_PAGE_CHARS = 25  # a page with less selectable text than this is treated as a scan
CACHE_DIR = ".sgpt-cache"


def _cache_file(path: Path) -> Path:
    stat = path.stat()
    key = hashlib.sha1(f"{path.name}|{stat.st_size}|{stat.st_mtime_ns}".encode()).hexdigest()[:16]
    return path.parent / CACHE_DIR / f"{key}.json"


def _read_pages(path: Path, ocr: bool = True) -> tuple[list[str], int]:
    """Return (text of each page, number of pages read with OCR).

    Pages without selectable text are OCR'd. OCR is slow, so results are cached in a hidden
    folder next to the PDF.
    """
    cache = _cache_file(path)
    if ocr and cache.exists():
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
            return data["pages"], data["ocr_pages"]
        except (OSError, ValueError, KeyError):
            pass
    try:
        import pymupdf
    except ImportError:
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Install a PDF library first: pip install pymupdf") from exc
        return [page.extract_text() or "" for page in PdfReader(str(path)).pages], 0

    from . import ocr as ocr_engine

    pages, ocr_pages = [], 0
    can_ocr = ocr and ocr_engine.available()
    with pymupdf.open(path) as doc:
        for page in doc:
            text = page.get_text("text", sort=True)
            if can_ocr and len(text.strip()) < MIN_PAGE_CHARS and page.get_images():
                text = ocr_engine.ocr_pdf_page(page)
                ocr_pages += 1
            pages.append(text)
    if ocr_pages:
        try:
            cache.parent.mkdir(exist_ok=True)
            cache.write_text(json.dumps({"pages": pages, "ocr_pages": ocr_pages}), encoding="utf-8")
        except OSError:
            pass  # read-only folder: just OCR again next time
    return pages, ocr_pages


def needs_ocr_but_unavailable(path: Path) -> bool:
    from . import ocr as ocr_engine

    if ocr_engine.available():
        return False
    pages, _ = _read_pages(path, ocr=False)
    return sum(len(p.strip()) for p in pages) < 200


def _strip_headers_footers(pages: list[str]) -> list[list[str]]:
    """Drop page numbers and lines repeated on most pages (running headers/footers)."""
    page_lines = [[ln.rstrip() for ln in page.splitlines()] for page in pages]
    if len(page_lines) >= 3:
        counts = Counter(ln.strip() for lines in page_lines for ln in set(lines) if ln.strip())
        repeated = {ln for ln, n in counts.items() if n >= max(3, len(page_lines) * 0.6)}
    else:
        repeated = set()
    return [
        [ln for ln in lines if ln.strip() not in repeated and not _PAGE_NUMBER.match(ln)]
        for lines in page_lines
    ]


def _clean(lines: list[str]) -> str:
    text = "\n".join(lines)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_questions(text: str) -> list[Question]:
    """Split paper text into top-level questions.

    Numbers must run in order (1, 2, 3...) so that numbered lists inside a question are
    not mistaken for new questions. One missing number is tolerated (OCR can miss one).
    Numbering may restart at 1 for a new chapter or paper in a compiled file: when a
    heading such as "Bab 3", "Chapter 2", "第三章" or a year comes just before it, or the
    "1" is near the top of a page. Lines "\\x01<n>" mark the start of page n.
    """
    questions: list[Question] = []
    current_num: int | None = None
    current_lines: list[str] = []
    start_page = page = 0
    section = first_heading = ""
    recent: list[str] = []      # the last few non-empty lines, to find headings
    lines_on_page = 0

    def flush() -> None:
        if current_num is None:
            return
        body = "\n".join(current_lines).strip()
        marks_found = [int(m) for m in _MARKS.findall(body)]
        questions.append(Question(str(current_num), body, sum(marks_found) or None, section, start_page))

    for line in text.splitlines():
        mark = _PAGE_MARK.match(line)
        if mark:
            page, lines_on_page = int(mark.group(1)), 0
            continue
        match = _QUESTION_WORD.match(line) or _QUESTION_NUM.match(line)
        if match:
            num = int(match.group(1))
            expected = 1 if current_num is None else current_num + 1
            heading = next((h for h in reversed(recent[-6:]) if len(h) < 90 and _SECTION.search(h)), "")
            restart = (num == 1 and current_num is not None and current_num >= 2
                       and (heading or (start_page < page and lines_on_page <= 8)))
            skipped = current_num is not None and current_num >= 3 and num == expected + 1
            if num == expected or restart or skipped:
                if heading and heading in (ln.strip() for ln in current_lines):
                    # the heading belongs to the next chapter, not the end of this question
                    cut = max(i for i, ln in enumerate(current_lines) if ln.strip() == heading)
                    current_lines = current_lines[:cut]
                flush()
                if current_num is None:
                    first_heading = heading
                if restart:
                    if not section:  # the file has chapters after all: name the first one too
                        for q in questions:
                            q.section = first_heading or "Part 1"
                    section = heading or f"Part {len({q.section for q in questions}) + 1}"
                current_num, start_page = num, page
                current_lines = [match.group(2)] if match.group(2) else []
                recent = []
                lines_on_page += 1
                continue
        if line.strip():
            recent.append(line.strip())
            lines_on_page += 1
        if current_num is not None:
            current_lines.append(line)
    flush()
    return questions


def extract_paper(path: Path, ocr: bool = True) -> ExamPaper:
    pages, ocr_pages = _read_pages(path, ocr)
    marked = _clean([ln for n, lines in enumerate(_strip_headers_footers(pages), 1)
                     for ln in [f"\x01{n}"] + lines + [""]])
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r"^\x01\d+$", "", marked, flags=re.M)).strip()
    title = next((ln.strip() for ln in text.splitlines() if ln.strip()), path.stem)
    return ExamPaper(path, title[:120], text, len(pages), split_questions(marked), ocr_pages)
