"""Convert documents between common formats, and export Markdown/text to Word, PDF or HTML.

Works with no extra software for PDF, Word (.docx), images, Markdown, text and HTML.
Older Office files (.doc, .rtf, .odt, PowerPoint, Excel) and the best-looking Word → PDF
conversion use LibreOffice when it is installed (free: https://www.libreoffice.org).
"""

from __future__ import annotations

import html as html_lib
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import markdown as md_lib

PDF = {".pdf"}
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
WORD = {".docx"}
OFFICE = {".doc", ".rtf", ".odt", ".pptx", ".ppt", ".odp", ".xlsx", ".xls", ".ods"}
MARKDOWN = {".md", ".markdown"}
TEXT = {".txt"}
HTML = {".html", ".htm"}
INPUTS = PDF | IMAGES | WORD | OFFICE | MARKDOWN | TEXT | HTML
TARGETS = {"pdf": "PDF", "docx": "Word (.docx)", "txt": "Text (.txt)", "md": "Markdown (.md)",
           "html": "Web page (.html)", "png": "Images (.png)"}

PAGE_CSS = """
body { font-family: serif; font-size: 10.5pt; line-height: 1.45; color: #111; }
h1 { font-size: 22pt; margin: 0 0 8pt; color: #1f3f7a; }
h2 { font-size: 15pt; margin: 16pt 0 6pt; color: #1f3f7a; border-bottom: 0.8pt solid #1f3f7a; padding-bottom: 2pt; }
h3 { font-size: 12pt; margin: 12pt 0 4pt; } h4 { font-size: 11pt; margin: 10pt 0 3pt; }
p { margin: 0 0 6pt; }
ul, ol { margin: 0 0 6pt 14pt; } li { margin: 0 0 2pt; }
blockquote { margin: 6pt 0 8pt; padding: 6pt 9pt; background-color: #f2f3f5; border: 0.6pt solid #b9bec7; }
blockquote p { margin: 0 0 2pt; }
table { border-collapse: collapse; margin: 6pt 0 8pt; width: 100%; }
th { border-top: 1pt solid #333; border-bottom: 0.6pt solid #333; padding: 3pt 5pt; text-align: left; }
td { border-bottom: 0.4pt solid #ccc; padding: 3pt 5pt; vertical-align: top; }
code, pre { font-family: monospace; font-size: 9.5pt; } hr { border: 0; border-top: 0.5pt solid #aaa; }
"""


class ConvertError(RuntimeError):
    pass


def targets_for(suffix: str) -> list[str]:
    suffix = suffix.lower()
    if suffix not in INPUTS or (suffix in OFFICE and not libreoffice()):
        return []  # old Office, PowerPoint and Excel files need LibreOffice
    return [t for t in TARGETS if not (suffix in PDF and t == "pdf")]


# --- Building blocks --------------------------------------------------------------------

def libreoffice() -> str | None:
    """Path to LibreOffice's soffice, if installed."""
    for name in ("soffice", "libreoffice"):
        if shutil.which(name):
            return shutil.which(name)
    for path in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                 r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                 "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(path).exists():
            return path
    return None


def _lo_convert(src: Path, fmt: str, out_dir: Path) -> Path:
    soffice = libreoffice()
    if not soffice:
        raise ConvertError(f"Converting {src.suffix} files needs LibreOffice (free): "
                           "https://www.libreoffice.org/download/")
    with tempfile.TemporaryDirectory() as profile:
        # A private profile lets this run even while LibreOffice is open.
        cmd = [soffice, f"-env:UserInstallation=file:///{Path(profile).as_posix().lstrip('/')}",
               "--headless", "--convert-to", fmt, "--outdir", str(out_dir), str(src)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=240)
        except (subprocess.SubprocessError, OSError) as exc:
            raise ConvertError(f"LibreOffice could not convert {src.name}: {exc}") from exc
    out = out_dir / f"{src.stem}.{fmt.split(':')[0]}"
    if not out.exists():
        raise ConvertError(f"LibreOffice could not convert {src.name}")
    return out


def keep_box_lines(text: str) -> str:
    """Each line of a "> " box stays on its own line (Markdown would join them)."""
    lines = text.split("\n")
    for i in range(len(lines) - 1):
        if lines[i].startswith(">") and lines[i + 1].startswith(">") and lines[i + 1][1:].strip() \
                and lines[i][1:].strip() and not lines[i].endswith("  "):
            lines[i] += "  "
    return "\n".join(lines)


def markdown_to_html(text: str, title: str = "") -> str:
    body = md_lib.markdown(keep_box_lines(text), extensions=["extra", "sane_lists"])
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{html_lib.escape(title)}"
            f"</title><style>{PAGE_CSS}</style></head><body>{body}</body></html>")


def html_to_pdf(page_html: str, out: Path, header: str = "") -> Path:
    """Lay out HTML on A4 pages; with a header, every page after the first gets a running
    header and all pages a centred page number, like a printed handout."""
    import pymupdf

    body = re.search(r"<body[^>]*>(.*)</body>", page_html, re.DOTALL | re.IGNORECASE)
    story = pymupdf.Story(html=body.group(1) if body else page_html, user_css=PAGE_CSS)
    writer = pymupdf.DocumentWriter(str(out))
    page = pymupdf.paper_rect("a4")
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(page + (56, 62, -56, -56))
        story.draw(device)
        writer.end_page()
    writer.close()
    if header:
        doc = pymupdf.open(out)
        if len(doc) > 1:
            for number, pg in enumerate(doc, 1):
                width = pg.rect.width
                if number > 1:
                    pg.insert_htmlbox(pymupdf.Rect(56, 26, width - 56, 44),
                                      f"<div style='font-size:8.5pt;color:#555;font-family:serif'>"
                                      f"{html_lib.escape(header)}</div>")
                    pg.draw_line((56, 44), (width - 56, 44), color=(0.6, 0.6, 0.6), width=0.4)
                pg.insert_htmlbox(pymupdf.Rect(56, pg.rect.height - 38, width - 56, pg.rect.height - 24),
                                  f"<div style='font-size:9pt;text-align:center;font-family:serif'>"
                                  f"– {number} –</div>")
            doc.saveIncr()
        doc.close()
    return out


_INLINE = re.compile(r"(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`)")


def _add_runs(paragraph, text: str) -> None:
    for piece in _INLINE.split(text):
        if not piece:
            continue
        if piece.startswith("**") and piece.endswith("**") and len(piece) > 4:
            paragraph.add_run(piece[2:-2]).bold = True
        elif piece.startswith("`") and piece.endswith("`"):
            paragraph.add_run(piece[1:-1]).font.name = "Consolas"
        elif piece.startswith("*") and piece.endswith("*") and len(piece) > 2:
            paragraph.add_run(piece[1:-1]).italic = True
        else:
            paragraph.add_run(piece)


def markdown_to_docx(text: str, out: Path, title: str = "") -> Path:
    """Write Markdown (headings, lists, quotes, tables, bold/italic) as a Word document."""
    import docx

    doc = docx.Document()
    if title:
        doc.core_properties.title = title
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        stripped = line.strip()
        if not stripped or stripped in ("---", "***"):
            i += 1
            continue
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{3}", lines[i + 1]):
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not re.match(r"^\s*\|?\s*:?-{3}", lines[i]):
                    rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            table = doc.add_table(rows=len(rows), cols=max(len(r) for r in rows))
            table.style = "Table Grid"
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    _add_runs(table.cell(r, c).paragraphs[0], cell)
            continue
        heading = re.match(r"^(#{1,6})\s+(.*)", stripped)
        if heading:
            level = min(len(heading.group(1)), 4)
            doc.add_heading(re.sub(r"\*\*(.+?)\*\*", r"\1", heading.group(2)), level=level - 1 if level > 1 else 0)
        elif re.match(r"^[-*+]\s+", stripped):
            _add_runs(doc.add_paragraph(style="List Bullet"), re.sub(r"^[-*+]\s+", "", stripped))
        elif re.match(r"^\d+[.)]\s+", stripped):
            _add_runs(doc.add_paragraph(style="List Number"), re.sub(r"^\d+[.)]\s+", "", stripped))
        elif stripped.startswith(">"):
            p = doc.add_paragraph(style="Quote")
            _add_runs(p, stripped.lstrip("> "))
        else:
            # Join hard-wrapped lines ("  " at the end) into one paragraph with line breaks.
            p = doc.add_paragraph()
            parts = [stripped]
            while line.endswith("  ") and i + 1 < len(lines) and lines[i + 1].strip():
                i += 1
                line = lines[i].rstrip("\n")
                parts.append(lines[i].strip())
            for n, part in enumerate(parts):
                if n:
                    p.add_run().add_break()
                _add_runs(p, part)
        i += 1
    doc.save(out)
    return out


def docx_to_markdown(path: Path) -> str:
    import docx

    doc = docx.Document(path)
    out = []
    for block in doc.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            para = docx.text.paragraph.Paragraph(block, doc)
            text = "".join(f"**{r.text}**" if r.bold and r.text.strip() else r.text for r in para.runs)
            text = text.strip()
            if not text:
                continue
            style = (para.style.name or "").lower() if para.style is not None else ""
            level = re.search(r"heading (\d)", style)
            if style == "title":
                out.append(f"# {para.text.strip()}")
            elif level:
                out.append(f"{'#' * (int(level.group(1)) + 1)} {para.text.strip()}")
            elif "list" in style:
                out.append(f"- {text}")
            else:
                out.append(text)
            out.append("")
        elif tag == "tbl":
            table = docx.table.Table(block, doc)
            rows = [[c.text.strip().replace("\n", " ") for c in row.cells] for row in table.rows]
            if rows:
                out.append("| " + " | ".join(rows[0]) + " |")
                out.append("|" + "---|" * len(rows[0]))
                out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                out.append("")
    return "\n".join(out).strip() + "\n"


def text_as_markdown(src: Path) -> str:
    """Readable Markdown for any supported input (OCR for images and scanned PDFs)."""
    s = src.suffix.lower()
    if s in MARKDOWN | TEXT:
        return src.read_text(encoding="utf-8", errors="replace")
    if s in HTML:
        from .sources import html_to_text

        title, text = html_to_text(src.read_text(encoding="utf-8", errors="replace"))
        return (f"# {title}\n\n" if title else "") + text.replace("\n", "\n\n")
    if s in WORD:
        return docx_to_markdown(src)
    if s in IMAGES:
        from . import ocr

        return ocr.ocr_document(src.name, src.read_bytes())[0]["text"]
    if s in PDF:
        from . import ocr

        pages = ocr.ocr_document(src.name, src.read_bytes()) if ocr.available() else None
        if pages is None:
            import pymupdf

            with pymupdf.open(src) as doc:
                pages = [{"page": i + 1, "text": p.get_text("text", sort=True)} for i, p in enumerate(doc)]
        if len(pages) == 1:
            return pages[0]["text"].strip() + "\n"
        return "\n\n".join(f"## Page {p['page']}\n\n{p['text'].strip()}" for p in pages) + "\n"
    if s in OFFICE:
        with tempfile.TemporaryDirectory() as tmp:
            return docx_to_markdown(_lo_convert(src, "docx", Path(tmp)))
    raise ConvertError(f"{src.name}: unsupported file type")


def images_to_pdf(images: list[Path], out: Path) -> Path:
    import pymupdf

    doc = pymupdf.open()
    for path in images:
        with pymupdf.open(path) as img:
            pdf_bytes = img.convert_to_pdf()
        with pymupdf.open("pdf", pdf_bytes) as page_doc:
            doc.insert_pdf(page_doc)
    doc.save(out, deflate=True)
    return out


def pdf_to_images(pdf: Path, out: Path, dpi: int = 150) -> Path:
    """Save every page as PNG: one .png for a single page, otherwise a .zip of them."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        if len(doc) == 1:
            out = out.with_suffix(".png")
            doc[0].get_pixmap(dpi=dpi).save(out)
            return out
        out = out.with_suffix(".zip")
        with zipfile.ZipFile(out, "w") as zf:
            for i, page in enumerate(doc, 1):
                zf.writestr(f"{pdf.stem}_page{i:03}.png", page.get_pixmap(dpi=dpi).tobytes("png"))
    return out


def merge_pdfs(files: list[Path], out: Path, work_dir: Path) -> Path:
    """Join files into one PDF; non-PDF files are converted first."""
    import pymupdf

    merged = pymupdf.open()
    for f in files:
        pdf = f if f.suffix.lower() in PDF else convert(f, "pdf", work_dir)
        with pymupdf.open(pdf) as doc:
            merged.insert_pdf(doc)
    merged.save(out, deflate=True)
    return out


def searchable_pdf(src: Path, out: Path, *, step=None, should_stop=None, dpi: int = 200) -> Path:
    """Scanned PDF or photo -> PDF with an invisible OCR text layer you can search and copy."""
    import pymupdf

    from . import ocr

    if ocr.available() != "rapidocr":
        raise ConvertError("Searchable PDFs need the built-in OCR: pip install rapidocr onnxruntime")
    if src.suffix.lower() in IMAGES:
        with pymupdf.open(src) as img:
            source = pymupdf.open("pdf", img.convert_to_pdf())
    else:
        source = pymupdf.open(src)
    result = pymupdf.open()
    result.insert_pdf(source)
    for i, page in enumerate(result):
        if should_stop and should_stop():
            raise InterruptedError()
        if step:
            step(i + 1, len(result))
        if len(page.get_text().strip()) >= 25:
            continue  # already has real text
        scale = 72 / dpi
        for box, text in ocr.ocr_boxes(page.get_pixmap(dpi=dpi).tobytes("png")):
            xs, ys = [p[0] * scale for p in box], [p[1] * scale for p in box]
            x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)
            height = max(y1 - y0, 4)
            font = "china-s" if re.search(r"[\u3400-\u9fff]", text) else "helv"
            size = height * 0.85
            width = pymupdf.get_text_length(text, fontname=font, fontsize=size) or 1
            origin = pymupdf.Point(x0, y1 - height * 0.2)
            page.insert_text(origin, text, fontsize=size, fontname=font, render_mode=3,
                             morph=(origin, pymupdf.Matrix((x1 - x0) / width, 1)))
    result.save(out, garbage=3, deflate=True)
    return out


# --- Main entry points ------------------------------------------------------------------

def convert(src: Path, target: str, out_dir: Path) -> Path:
    """Convert one file. Returns the path of the new file in out_dir."""
    s = src.suffix.lower()
    if s not in INPUTS:
        raise ConvertError(f"{src.name}: unsupported file type")
    if target not in TARGETS:
        raise ConvertError(f"Unknown target format: {target}")
    out = out_dir / f"{src.stem}.{target}"
    if out.resolve() == src.resolve():
        out = out_dir / f"{src.stem} (converted).{target}"

    if target == "pdf":
        if s in PDF:
            return Path(shutil.copy(src, out))
        if s in IMAGES:
            return images_to_pdf([src], out)
        if s in WORD | OFFICE and libreoffice():
            converted = _lo_convert(src, "pdf", out_dir)
            return converted if converted == out else Path(shutil.move(converted, out))
        if s in HTML:
            return html_to_pdf(src.read_text(encoding="utf-8", errors="replace"), out)
        return html_to_pdf(markdown_to_html(text_as_markdown(src), src.stem), out)
    if target == "docx":
        if s in WORD:
            return Path(shutil.copy(src, out))
        if s in OFFICE:
            converted = _lo_convert(src, "docx", out_dir)
            return converted if converted == out else Path(shutil.move(converted, out))
        if s in PDF:
            try:
                from pdf2docx import Converter
            except ImportError:
                Converter = None
            has_text = _pdf_has_text(src)
            if Converter and has_text:
                conv = Converter(str(src))
                try:
                    conv.convert(str(out))
                finally:
                    conv.close()
                return out
        return markdown_to_docx(text_as_markdown(src), out, src.stem)
    if target in ("txt", "md"):
        text = text_as_markdown(src)
        if target == "txt":
            text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        out.write_text(text, encoding="utf-8")
        return out
    if target == "html":
        if s in HTML:
            return Path(shutil.copy(src, out))
        out.write_text(markdown_to_html(text_as_markdown(src), src.stem), encoding="utf-8")
        return out
    # png
    pdf = src if s in PDF else convert(src, "pdf", out_dir)
    return pdf_to_images(pdf, out)


def _pdf_has_text(path: Path) -> bool:
    import pymupdf

    with pymupdf.open(path) as doc:
        return sum(len(p.get_text().strip()) for p in doc) > 50 * max(len(doc), 1) * 0.2


def export_markdown(text: str, fmt: str, title: str = "") -> tuple[bytes, str]:
    """Markdown -> (file bytes, media type) for downloads."""
    if fmt == "md":
        return text.encode("utf-8"), "text/markdown"
    if fmt == "txt":
        plain = re.sub(r"\*\*(.+?)\*\*", r"\1", re.sub(r"(?m)^#{1,6}\s+", "", text))
        return plain.encode("utf-8"), "text/plain"
    if fmt == "html":
        return markdown_to_html(text, title).encode("utf-8"), "text/html"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / f"export.{fmt}"
        if fmt == "pdf":
            html_to_pdf(markdown_to_html(text, title), out, header=title)
            return out.read_bytes(), "application/pdf"
        if fmt == "docx":
            markdown_to_docx(text, out, title)
            return out.read_bytes(), ("application/vnd.openxmlformats-officedocument."
                                      "wordprocessingml.document")
    raise ConvertError(f"Unknown export format: {fmt}")


def main(argv: list[str] | None = None) -> int:
    """python -m sgpt.convert report.docx --to pdf"""
    import argparse
    import sys

    p = argparse.ArgumentParser(prog="sgpt.convert", description="Convert documents.")
    p.add_argument("files", nargs="+", help="files to convert")
    p.add_argument("--to", required=True, choices=[*TARGETS, "merged-pdf", "searchable-pdf"],
                   help="target format; merged-pdf joins all files into one PDF")
    p.add_argument("-o", "--out-dir", default=".", help="where to save (default: current folder)")
    args = p.parse_args(argv)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        if args.to == "merged-pdf":
            print(merge_pdfs([Path(f) for f in args.files], out_dir / "merged.pdf", out_dir))
            return 0
        for f in args.files:
            src = Path(f)
            if args.to == "searchable-pdf":
                print(searchable_pdf(src, out_dir / f"{src.stem} (searchable).pdf"))
            else:
                print(convert(src, args.to, out_dir))
    except (ConvertError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
