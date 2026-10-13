import time

from sgpt import study
from sgpt.app import create_app
from sgpt.providers import make_client
from sgpt.sources import Source


def _client(host):
    return make_client("ollama", base_url=host, verbose=False)


def test_each_study_tool(fake_ai):
    c = _client(fake_ai[0])
    src = [Source("text", "Pasted text", "Photosynthesis makes glucose. " * 20)]
    notes = study.generate(c, "notes", src, {"topic": "Photosynthesis", "style": "chapter"})
    assert notes["markdown"].startswith("# Photosynthesis") and notes["title"] == "Photosynthesis"

    cards = study.generate(c, "flashcards", src, {"topic": "x", "count": 20})
    assert len(cards["cards"]) == 20 and cards["cards"][0] == {"front": "Term 0", "back": "Meaning 0"}
    assert study.as_csv(cards).splitlines()[0] == "Term 0,Meaning 0"

    vocab = study.generate(c, "vocab", [], {"words": "osmosis, diffusion", "translate_to": "zh"})
    assert [w["word"] for w in vocab["words"]] == ["osmosis", "diffusion"]
    assert "| Word | Type | Meaning | Example | Translation |" in study.as_markdown(vocab)

    quiz = study.generate(c, "quiz", src, {"topic": "x", "count": 5})
    # the check corrected item 1's key and dropped broken item 2; more were written to refill
    assert len(quiz["items"]) == 5
    assert any(q.get("checked") == "corrected" and q["answer"] == 1 for q in quiz["items"])
    assert all(len(q["options"]) == 4 for q in quiz["items"])

    tenses = study.generate(c, "grammar", [], {"test": "en_tenses", "count": 3})
    assert tenses["items"][0]["type"] == "fill" and tenses["items"][0]["answer"] == "fixed"
    assert "went" in tenses["items"][0]["alternatives"]
    malay = study.generate(c, "grammar", [], {"test": "ms_error", "count": 3})
    item = malay["items"][0]
    assert item["type"] == "error" and len(item["segments"]) == 4 and item["correction"] == "pelajaran"
    assert "**C → pelajaran**" in study.as_markdown(malay) or "B → pelajaran" in study.as_markdown(malay)


def test_study_guide_uses_question_bank(fake_ai):
    c = _client(fake_ai[0])
    bank = {"chapters": ["Algebra", "Geometry"], "papers": ["p1.pdf"], "questions": [
        {"chapter": "Algebra", "paper": "p1.pdf", "number": "1", "text": "Solve x", "marks": 2, "difficulty": 3},
        {"chapter": "Algebra", "paper": "p1.pdf", "number": "2", "text": "Expand", "marks": 4, "difficulty": 8},
        {"chapter": "Geometry", "paper": "p1.pdf", "number": "3", "text": "Area", "marks": 3, "difficulty": 5}]}
    guide = study.generate(c, "notes", [], {"topic": "Maths", "style": "guide", "bank": bank})
    md = guide["markdown"]
    assert md.startswith("# Maths — Study Guide")
    assert "| Algebra | 2 | 6 | 5.5/10 | p1.pdf Q2 (8/10) |" in md
    assert "## 1. Algebra" in md and "> key fact about Algebra" in md and "## 2. Geometry" in md
    assert "- [ ] Algebra" in md and "## Must memorise" in md


def test_study_endpoints(fake_ai, tmp_path):
    c = create_app(tmp_path / "lib", tmp_path / "out", fake_ai[0]).test_client()

    def wait(job):
        while job["state"] == "running":
            time.sleep(0.05)
            job = c.get(f"/api/jobs/{job['id']}").get_json()
        return job

    job = wait(c.post("/api/study/generate", json={"kind": "notes", "topic": "Photosynthesis",
                                                   "text": "Plants make glucose. " * 30, "style": "mindmap"}).get_json())
    assert job["state"] == "done", job
    notes = c.get(f"/api/study/{job['result']['id']}").get_json()
    assert "<table>" in notes["html"] and notes["sources"][0]["kind"] == "text"
    job = wait(c.post(f"/api/study/{notes['id']}/ask", json={"question": "What absorbs light?"}).get_json())
    assert "<strong>light</strong>" in job["result"]["html"]
    assert c.get(f"/api/study/{notes['id']}").get_json()["qa"][0]["question"] == "What absorbs light?"
    assert c.get(f"/api/study/{notes['id']}/export?format=docx").data[:2] == b"PK"
    assert c.get(f"/api/study/{notes['id']}/export?format=csv").status_code == 400

    job = wait(c.post("/api/study/generate", json={"kind": "grammar", "test": "en_word_form", "count": 4}).get_json())
    assert job["state"] == "done", job
    listed = c.get("/api/study").get_json()
    assert [x["kind"] for x in listed] == ["grammar", "notes"] and listed[0]["size"] >= 3
    assert c.delete(f"/api/study/{listed[0]['id']}").status_code == 200
