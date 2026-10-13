from exam_gen.cli import main
from exam_gen.ollama_client import parse_json, strip_thinking
from exam_gen.pdf_extract import extract_paper, split_questions


def test_extracts_questions_and_marks(sample_pdf):
    paper = extract_paper(sample_pdf / "maths_2023.pdf")
    assert paper.page_count == 2
    assert [q.number for q in paper.questions] == ["1", "2", "3", "4"]
    assert [q.marks for q in paper.questions] == [2, 3, 3, 3]
    assert "Page 1 of 2" not in paper.text


def test_numbered_list_inside_question_is_not_a_new_question():
    qs = split_questions("1. First question\n2. Second\nSteps:\n1. do this\n3. Third")
    assert [q.number for q in qs] == ["1", "2", "3"]


def test_strip_thinking_and_parse_json():
    assert strip_thinking("<think>reasoning</think>\nHello") == "Hello"
    assert strip_thinking("Hi <think>never closed") == "Hi"
    assert parse_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_end_to_end_writes_markdown(sample_pdf, fake_ollama, tmp_path):
    host, requests = fake_ollama
    out = tmp_path / "exam.md"
    assert main([str(sample_pdf), "--host", host, "-o", str(out), "--seed", "1", "-q"]) == 0
    md = out.read_text()
    assert "# GCSE Mathematics — Practice Exam Paper" in md
    assert "**Question 1**" in md and "# Marking Scheme" in md
    assert "x = 4" in md and "hidden" not in md
    assert all(r["model"] == "qwen3:4b" and r["think"] is False for r in requests)


def test_missing_model_gives_helpful_error(sample_pdf, fake_ollama, capsys):
    host, _ = fake_ollama
    assert main([str(sample_pdf), "--host", host, "-m", "llama3:8b", "-q"]) == 2
    assert "ollama pull llama3:8b" in capsys.readouterr().err
