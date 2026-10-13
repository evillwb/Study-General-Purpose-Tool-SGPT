import json
from pathlib import Path

import pymupdf
import pytest

from sgpt import sources
from sgpt.cli import main, parse_plan
from sgpt.generator import render_markdown
from sgpt.ollama_client import parse_json, strip_thinking
from sgpt.pdf_extract import extract_paper, split_questions
from sgpt.providers import OpenAICompatClient, make_client, save_provider_config


def test_extracts_questions_and_marks(sample_pdf):
    paper = extract_paper(sample_pdf / "maths_2023.pdf")
    assert paper.page_count == 2
    assert [q.number for q in paper.questions] == ["1", "2", "3", "4"]
    assert [q.marks for q in paper.questions] == [2, 3, 3, 3]
    assert "Page 1 of 2" not in paper.text
    assert paper.ocr_pages == 0


def test_numbered_list_inside_question_is_not_a_new_question():
    qs = split_questions("1. First question\n2. Second\nSteps:\n1. do this\n3. Third")
    assert [q.number for q in qs] == ["1", "2", "3"]


def test_strip_thinking_and_parse_json():
    assert strip_thinking("<think>reasoning</think>\nHello") == "Hello"
    assert strip_thinking("Hi <think>never closed") == "Hi"
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_ocr_reads_scanned_pdf(tmp_path):
    page = pymupdf.open().new_page()
    for i, line in enumerate(["1. State Newton's second law of motion. [2 marks]",
                              "2. Calculate the speed of a car that travels 100 m in 5 s. [3 marks]",
                              "3. Define the term momentum. [1 mark]"]):
        page.insert_text((50, 80 + 30 * i), line, fontsize=12)
    scan = pymupdf.open()
    scan.new_page().insert_image(scan[0].rect, stream=page.get_pixmap(dpi=150).tobytes("png"))
    scan.save(tmp_path / "scan.pdf")

    paper = extract_paper(tmp_path / "scan.pdf")
    assert paper.ocr_pages == 1
    assert "Newton" in paper.text
    assert [q.marks for q in paper.questions] == [2, 3, 1]
    source = sources.load_file(tmp_path / "scan.pdf")
    assert source.kind == "paper" and source.ocr


def test_cli_matches_past_paper_layout(sample_pdf, fake_ai, tmp_path):
    host, server = fake_ai
    out = tmp_path / "exam.md"
    assert main([str(sample_pdf), "--base-url", host, "-o", str(out), "--seed", "1", "-q"]) == 0
    md = out.read_text()
    assert "# GCSE Mathematics — Practice Exam" in md
    assert "## Section A" in md and "**4.**" in md
    assert "# Model Answers" in md and "# Marking Scheme" in md
    assert "correct method — **1 mark**" in md and "plan" not in md
    exam = json.loads(out.with_suffix(".json").read_text())
    assert len(exam["questions"]) == 4
    assert all(r["model"] == "qwen3:4b" for r in server.requests)
    # thinking is only switched on for the double-check
    for r in server.requests:
        assert r["think"] is ("independent" in r["messages"][0]["content"])
    qs = exam["questions"]
    assert [q["check"] for q in qs] == ["verified", "corrected", "verified", "verified"]
    assert qs[1]["final_answer"] == "x = 3.5" and qs[1]["marking_points"][0]["marks"] == 3
    # question 3 failed the check, so it was rewritten
    assert "2x + 3" not in qs[2]["question"]


def test_cli_custom_plan_from_notes(fake_ai, tmp_path):
    host, _ = fake_ai
    notes = tmp_path / "notes.txt"
    notes.write_text("Photosynthesis happens in chloroplasts. " * 20)
    out = tmp_path / "bio.md"
    rc = main([str(tmp_path / "missing"), "--text-file", str(notes), "--topic", "Photosynthesis",
               "--plan", "mcq:6,short:2:4", "--base-url", host, "-o", str(out), "-q"])
    assert rc == 0
    exam = json.loads(out.with_suffix(".json").read_text())
    qs = exam["questions"]
    assert [q["type"] for q in qs] == ["mcq"] * 6 + ["short"] * 2
    assert qs[0]["options"] == ["1", "2", "3.5", "4"]  # letter prefixes stripped
    assert qs[-1]["marks"] == 4 and qs[-1]["answer"] == "2x = 7, so x = 3.5"  # fixed by the check
    assert [s["name"] for s in exam["sections"]] == ["Section A: Multiple choice",
                                                     "Section B: Short answer"]
    assert "Plants make glucose" in exam["context"]["notes"]
    md = out.read_text()
    assert "\n\nA. 1  \nB. 2" in md  # options on their own lines


def test_parse_plan_rejects_unknown_types():
    assert parse_plan("mcq:3,essay:1:15") == [{"type": "mcq", "count": 3},
                                              {"type": "essay", "count": 1, "marks": 15}]
    with pytest.raises(Exception):
        parse_plan("riddle:2")


def test_missing_model_gives_helpful_error(sample_pdf, fake_ai, capsys):
    host, _ = fake_ai
    assert main([str(sample_pdf), "--base-url", host, "-m", "llama3:8b", "-q"]) == 2
    assert "ollama pull llama3:8b" in capsys.readouterr().err


def test_openai_compatible_client_drops_rejected_options(fake_ai):
    host, server = fake_ai
    server.reject_temperature = True
    client = OpenAICompatClient(host + "/v1", "good-key", "gpt-test", label="Test")
    assert client.list_models() == ["gpt-test"]  # embedding models filtered out
    assert client.chat("You are a helper.", "hi") == "OK"
    last = server.requests[-1]
    assert "temperature" not in last and last["max_tokens"] == 4096


def test_openai_bad_key_message(fake_ai):
    client = OpenAICompatClient(fake_ai[0] + "/v1", "bad", "gpt-test", label="Test")
    with pytest.raises(Exception, match="rejected the API key"):
        client.check_model()


def test_anthropic_client_uses_sdk_streaming(fake_ai, monkeypatch):
    host, server = fake_ai
    monkeypatch.setenv("ANTHROPIC_BASE_URL", host)
    save_provider_config("anthropic", api_key="sk-ant-test-key-1234")
    client = make_client("anthropic")
    assert client.model == "claude-opus-5-5"
    assert client.list_models() == ["claude-opus-5-5"]
    reply = client.chat("You are a senior examiner.", "Question 1 [2 marks] (Short answer)\nx",
                        json_mode=True)
    assert json.loads(reply)["solutions"][0]["final_answer"] == "x = 4"
    req = server.requests[-1]
    assert "temperature" not in req
    assert req["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in req["headers"].get("anthropic-beta", "")
    assert req["output_config"] == {"effort": "high"}


def test_web_search_reads_pages_and_wikipedia(monkeypatch):
    ddg = ('<a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2F'
           'example.org%2Fphoto&amp;rut=x">Photosynthesis <b>basics</b></a>'
           '<a class="result__a" href="https://www.youtube.com/watch?v=1">Video</a>')
    page = ("<html><head><title>Photosynthesis basics</title><script>x()</script></head><body>"
            "<nav>Home | About</nav><p>" + "Plants convert light energy into chemical energy. " * 10
            + "</p></body></html>")
    calls = []

    def fake_get(url, data=None, headers=None, timeout=20):
        calls.append(url)
        if "duckduckgo" in url:
            return ddg.encode(), "text/html"
        if "example.org" in url:
            return page.encode(), "text/html"
        if "list=search" in url:
            return json.dumps({"query": {"search": [{"title": "Photosynthesis"}]}}).encode(), "json"
        if "prop=extracts" in url:
            return json.dumps({"query": {"pages": {"1": {"extract": "Photosynthesis is... " * 40}}}}).encode(), "json"
        raise sources.SourceError("unexpected " + url)

    monkeypatch.setattr(sources, "_get", fake_get)
    found = sources.web_search("photosynthesis", warn=lambda m: None)
    assert [s.title for s in found] == ["Photosynthesis basics", "Photosynthesis - Wikipedia"]
    assert "Home | About" not in found[0].text and "x()" not in found[0].text
    assert not any("youtube" in c for c in calls)


def test_gather_sources_searches_only_when_nothing_else(monkeypatch, tmp_path):
    monkeypatch.setattr(sources, "web_search", lambda q, **k: [sources.Source("web", "W", "web text")])
    assert [s.kind for s in sources.gather_sources(topic="cells")] == ["web"]
    got = sources.gather_sources(text="my notes " * 30, topic="cells")
    assert [s.kind for s in got] == ["text"]
    got = sources.gather_sources(text="my notes " * 30, topic="cells", web="on")
    assert [s.kind for s in got] == ["text", "web"]
    with pytest.raises(sources.SourceError):
        sources.gather_sources(topic="")

    def offline(q, **k):
        raise sources.SourceError("No web results could be read.")

    monkeypatch.setattr(sources, "web_search", offline)
    warnings = []
    assert sources.gather_sources(topic="cells", warn=warnings.append) == []
    assert "AI's own knowledge" in warnings[0]


def test_render_markdown_parts():
    exam = {"title": "T", "duration_minutes": 30, "instructions": ["Answer all."],
            "sections": [{"name": "S", "instructions": "Do it."}], "sources": [],
            "created": "2026-01-01T10:00:00", "model": "m",
            "questions": [{"number": 1, "section": 0, "type": "short", "marks": 2,
                           "question": "Line one\nLine two", "options": [], "parts": [],
                           "answer": "A", "final_answer": "F", "accept": "",
                           "marking_points": [{"point": "p", "marks": 2}]}]}
    paper = render_markdown(exam, "paper")
    assert "Line one  \nLine two" in paper and "Model Answers" not in paper
    assert "**Final answer:** F" in render_markdown(exam, "answers")
    assert "- p — **2 marks**" in render_markdown(exam, "scheme")


def test_detects_chinese_and_malay_questions():
    zh = "第1题 解方程 3x + 5 = 20。（2分）\n2．计算圆的面积。【3分】\n3、写出牛顿第二定律。（2 分）"
    assert [(q.number, q.marks) for q in split_questions(zh)] == [("1", 2), ("2", 3), ("3", 2)]
    ms = "Soalan 1\nSelesaikan 3x + 5 = 20. [2 markah]\nSoalan 2 Hitung luas bulatan. (3 markah)"
    assert [(q.number, q.marks) for q in split_questions(ms)] == [("1", 2), ("2", 3)]
    # a decimal at the start of a line is not a new question
    en = "1. Mass is 3.5 kg [2]\n3.5 kg is a line\n2. Next (4 marks)"
    assert [(q.number, q.marks) for q in split_questions(en)] == [("1", 2), ("2", 4)]


def test_chinese_exam_language(fake_ai, tmp_path):
    host, server = fake_ai
    notes = tmp_path / "notes.txt"
    notes.write_text("Photosynthesis happens in chloroplasts. " * 20)
    out = tmp_path / "zh.md"
    rc = main([str(tmp_path / "none"), "--text-file", str(notes), "--topic", "光合作用",
               "--plan", "true_false:2,short:1", "--language", "zh", "--source-language", "en",
               "--base-url", host, "-o", str(out), "-q"])
    assert rc == 0
    exam = json.loads(out.with_suffix(".json").read_text())
    assert exam["language"] == "zh" and exam["title"] == "光合作用 — 模拟试卷"
    assert exam["questions"][0]["options"] == ["对", "错"]
    assert exam["sections"][0]["name"] == "A 部分：判断题"
    md = out.read_text()
    for heading in ("考生须知", "# 参考答案", "# 评分标准", "### 第 1 题 — 1 分"):
        assert heading in md
    writer = next(r for r in server.requests if "brand-new" in r["messages"][0]["content"])
    assert "Simplified Chinese" in writer["messages"][0]["content"]
    assert "source material is in English" in writer["messages"][0]["content"]


def test_difficulty_targets_and_custom_mix():
    from sgpt.generator import difficulty_targets, normalise_mix
    assert difficulty_targets(5, {"easy": 30, "medium": 50, "hard": 20}) == \
        ["easy", "easy", "medium", "medium", "hard"]
    assert difficulty_targets(3, {"easy": 0, "medium": 0, "hard": 100}) == ["hard"] * 3
    assert normalise_mix({"easy": 1, "medium": 1, "hard": 1}) == {"easy": 33, "medium": 34, "hard": 33}
    assert normalise_mix({"easy": 0, "medium": 0, "hard": 0}) is None


def test_compiled_chapters_are_all_found_and_analysed(tmp_path):
    """A 60-page file of every chapter's past-year questions, numbering restarting at 1."""
    import pymupdf

    from sgpt.generator import MAX_PARTS, analysis_steps, paper_parts
    from sgpt.sources import Source

    doc = pymupdf.open()
    for chapter in range(1, 13):
        for page in range(5):
            lines = [f"Bab {chapter} Topik {chapter}"] if page == 0 else []
            for q in range(1, 4):
                n = page * 3 + q
                lines.append(f"{n}. Chapter {chapter} question {n}: " + "explain this idea " * 12 + "[4 markah]")
            doc.new_page().insert_textbox(pymupdf.Rect(40, 40, 560, 800), "\n".join(lines), fontsize=9)
    doc.save(tmp_path / "all_chapters.pdf")

    paper = extract_paper(tmp_path / "all_chapters.pdf")
    assert len(paper.questions) == 12 * 15
    assert paper.questions[-1].section == "Bab 12 Topik 12" and paper.questions[-1].page == 60
    assert paper.questions[0].section == "Bab 1 Topik 1"

    parts = paper_parts(paper, 12000)
    assert 1 < len(parts) <= MAX_PARTS
    joined = "\n".join(parts)
    assert "=== Bab 12 Topik 12 ===" in joined and "Chapter 12 question 15" in joined  # the end is read too
    source = Source("paper", "all_chapters.pdf", paper.text, paper=paper)
    assert analysis_steps([source], 12000) == len(parts)
