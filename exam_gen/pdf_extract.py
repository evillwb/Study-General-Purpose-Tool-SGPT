"""Extract text and a rough question structure from past-paper PDFs."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Question:
    number: str
    text: str
    marks: int | None = None


@dataclass
class ExamPaper:
    path: Path
    title: str
    text: str
    page_count: int
    questions: list[Question] = field(default_factory=list)

    @property
    def total_marks(self) -> int | None:
        marks = [q.marks for q in self.questions if q.marks is not None]
        return sum(marks) if marks else None


# "Question 3", "Q3", "Q.3"
_QUESTION_WORD = re.compile(r"^\s*(?:question|q\.?)\s*(\d{1,2})\b[.):]?\s*(.*)$", re.IGNORECASE)
# "3." or "3)" at the start of a line, followed by text
_QUESTION_NUM = re.compile(r"^\s*(\d{1,2})[.)]\s+(\S.*)$")
# "[5 marks]", "(5 marks)", "[5]", "(Total 12 marks)"
_MARKS = re.compile(
    r"[\[(]\s*(?:total\s*(?:for\s*question\s*\d+\s*(?:is|=)?\s*)?:?\s*)?(\d{1,3})\s*(?:marks?|m)?\s*[\])]",
    re.IGNORECASE,
)
_PAGE_NUMBER = re.compile(r"^\s*(?:page\s*)?\d{1,3}(?:\s*(?:of|/)\s*\d{1,3})?\s*$", re.IGNORECASE)


def _read_pages(path: Path) -> list[str]:
    """Return the text of each page, preferring PyMuPDF and falling back to pypdf."""
    try:
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            return [page.get_text("text", sort=True) for page in doc]
    except ImportError:
        pass
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Install a PDF library first: pip install pymupdf") from exc
    return [page.extract_text() or "" for page in PdfReader(str(path)).pages]


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

    Numbers must run in order (1, 2, 3...) so that numbered lists inside a
    question are not mistaken for new questions.
    """
    questions: list[Question] = []
    current_num: int | None = None
    current_lines: list[str] = []

    def flush() -> None:
        if current_num is None:
            return
        body = "\n".join(current_lines).strip()
        marks_found = [int(m) for m in _MARKS.findall(body)]
        questions.append(Question(str(current_num), body, sum(marks_found) or None))

    for line in text.splitlines():
        match = _QUESTION_WORD.match(line) or _QUESTION_NUM.match(line)
        if match:
            num = int(match.group(1))
            expected = 1 if current_num is None else current_num + 1
            if num == expected:
                flush()
                current_num = num
                current_lines = [match.group(2)] if match.group(2) else []
                continue
        if current_num is not None:
            current_lines.append(line)
    flush()
    return questions


def extract_paper(path: Path) -> ExamPaper:
    pages = _read_pages(path)
    text = _clean([ln for lines in _strip_headers_footers(pages) for ln in lines + [""]])
    title = next((ln.strip() for ln in text.splitlines() if ln.strip()), path.stem)
    return ExamPaper(path, title[:120], text, len(pages), split_questions(text))


def load_papers(folder: Path) -> list[ExamPaper]:
    pdfs = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".pdf")
    papers = []
    for pdf in pdfs:
        paper = extract_paper(pdf)
        if len(paper.text) < 200:
            print(f"  ! {pdf.name}: little or no text found (scanned image PDF?) - skipped")
            continue
        papers.append(paper)
    return papers
