import io
import time
import zipfile

import docx
import pymupdf
import pytest

from sgpt import convert
from sgpt.app import create_app

NOTES = "# Photosynthesis 光合作用\n\nPlants make **glucose**.\n\n- light\n- 水\n\n| A | B |\n|---|---|\n| 1 | 2 |\n"


def _scan(path, lines):
    page = pymupdf.open().new_page()
    for i, line in enumerate(lines):
        page.insert_text((50, 80 + 30 * i), line, fontsize=13)
    scan = pymupdf.open()
    scan.new_page().insert_image(scan[0].rect, stream=page.get_pixmap(dpi=150).tobytes("png"))
    scan.save(path)
    return path


def test_markdown_to_every_format(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text(NOTES, encoding="utf-8")
    pdf = convert.convert(src, "pdf", tmp_path)
    assert "光合作用" in pymupdf.open(pdf)[0].get_text()
    word = docx.Document(convert.convert(src, "docx", tmp_path))
    assert word.paragraphs[0].text == "Photosynthesis 光合作用"
    assert any(r.bold and r.text == "glucose" for p in word.paragraphs for r in p.runs)
    assert word.tables[0].cell(1, 1).text == "2"
    assert "<strong>glucose</strong>" in convert.convert(src, "html", tmp_path).read_text()
    assert "**" not in convert.convert(src, "txt", tmp_path).read_text()


def test_word_round_trip_and_images(tmp_path):
    src = tmp_path / "notes.md"
    src.write_text(NOTES, encoding="utf-8")
    word = convert.convert(src, "docx", tmp_path)
    back = convert.docx_to_markdown(word)
    assert back.startswith("# Photosynthesis") and "**glucose**" in back and "| 1 | 2 |" in back
    (tmp_path / "out").mkdir()
    pdf = convert.convert(word, "pdf", tmp_path / "out")  # LibreOffice if present, else built in
    assert "Plants make" in pymupdf.open(pdf)[0].get_text()
    png = convert.convert(pdf, "png", tmp_path)
    assert png.suffix == ".png"
    two = convert.merge_pdfs([pdf, png], tmp_path / "merged.pdf", tmp_path / "out")
    assert len(pymupdf.open(two)) == 2
    assert zipfile.is_zipfile(convert.convert(two, "png", tmp_path))


def test_scan_to_word_and_searchable_pdf(tmp_path):
    scan = _scan(tmp_path / "scan.pdf", ["1. Define momentum. [1 mark]", "2. State Ohm's law. [2 marks]"])
    word = docx.Document(convert.convert(scan, "docx", tmp_path))  # OCR, not pdf2docx
    assert "momentum" in "\n".join(p.text for p in word.paragraphs)
    out = convert.searchable_pdf(scan, tmp_path / "searchable.pdf")
    page = pymupdf.open(out)[0]
    assert "Ohm" in page.get_text() and page.get_images()  # text layer on top of the scan


def test_unsupported_file(tmp_path):
    bad = tmp_path / "x.exe"
    bad.write_bytes(b"MZ")
    with pytest.raises(convert.ConvertError):
        convert.convert(bad, "pdf", tmp_path)


def test_convert_and_export_endpoints(tmp_path):
    c = create_app(tmp_path / "lib", tmp_path / "out").test_client()
    job = c.post("/api/convert", data={"target": "docx",
                                       "files": [(io.BytesIO(NOTES.encode()), "a.md")]}).get_json()
    deadline = time.time() + 30
    while job["state"] == "running" and time.time() < deadline:
        time.sleep(0.1)
        job = c.get(f"/api/jobs/{job['id']}").get_json()
    assert job["state"] == "done", job
    [result] = job["result"]
    r = c.get(result["url"])
    assert r.status_code == 200 and r.data[:2] == b"PK"
    assert c.get(f"/api/converted/{job['id']}/../../secret").status_code == 404
    assert c.post("/api/convert", data={"target": "pdf",
                                        "files": [(io.BytesIO(b"x"), "v.exe")]}).status_code == 400

    r = c.post("/api/export", json={"markdown": "# Hi\n\nText", "format": "pdf", "title": "OCR 结果"})
    assert r.status_code == 200 and r.data[:4] == b"%PDF"
    assert "filename*=UTF-8''OCR%20%E7%BB%93%E6%9E%9C.pdf" in r.headers["Content-Disposition"]
