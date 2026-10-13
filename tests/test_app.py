import io
import time

from sgpt.app import create_app


def _wait(client, job_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").get_json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_full_flow(sample_pdf, fake_ai, tmp_path):
    host, server = fake_ai
    app = create_app(tmp_path / "lib", tmp_path / "out", host)
    c = app.test_client()

    assert c.get("/").status_code == 200
    meta = c.get("/api/meta").get_json()
    assert [t["id"] for t in meta["question_types"]][:2] == ["mcq", "true_false"]
    assert c.get("/api/status?provider=ollama").get_json()["models"] == ["qwen3:4b"]

    pdf = (sample_pdf / "maths_2023.pdf").read_bytes()
    assert c.post("/api/library", data={"files": (io.BytesIO(pdf), "maths 2023.pdf")}).status_code == 200
    [item] = c.get("/api/library").get_json()
    assert item["role"] == "paper" and item["questions"] == 4 and item["use"]

    # Match the past paper's layout
    job = c.post("/api/generate", json={"structure": "match", "seed": "3"}).get_json()
    job = _wait(c, job["id"])
    assert job["state"] == "done", job
    assert "Analysing maths 2023.pdf" in job["log"]
    exam = c.get(f"/api/exams/{job['exam_id']}").get_json()
    assert exam["title"] == "GCSE Mathematics — Practice Exam"
    assert len(exam["questions"]) == 4 and exam["total_marks"] == 12
    assert "Model Answers" in exam["html"]["answers"] and "Marking Scheme" in exam["html"]["scheme"]
    assert "Marking Scheme" not in exam["html"]["paper"]
    assert "context" not in exam

    # Edit, regenerate and delete questions
    x = c.patch(f"/api/exams/{exam['id']}/questions/2", json={"question": "New <b>text</b>"}).get_json()
    assert x["questions"][1]["question"] == "New <b>text</b>"
    assert "&lt;b&gt;" in x["html"]["paper"]  # raw HTML from users or the AI is escaped
    job = c.post(f"/api/exams/{exam['id']}/questions/2/regenerate", json={}).get_json()
    assert _wait(c, job["id"])["state"] == "done"
    x = c.get(f"/api/exams/{exam['id']}").get_json()
    assert x["questions"][1]["question"].startswith("Solve") and x["questions"][1]["number"] == 2
    x = c.delete(f"/api/exams/{exam['id']}/questions/1").get_json()
    assert [q["number"] for q in x["questions"]] == [1, 2, 3]

    r = c.get(f"/api/exams/{exam['id']}/export?part=scheme")
    assert r.status_code == 200 and r.data.decode().startswith("# Marking Scheme")
    assert "attachment" in r.headers["Content-Disposition"]
    assert c.patch(f"/api/exams/{exam['id']}", json={"title": "Mock 1"}).get_json()["title"] == "Mock 1"
    [listed] = c.get("/api/exams").get_json()
    assert listed["title"] == "Mock 1" and listed["questions"] == 3

    # Custom plan, with the past paper switched to "notes"
    assert c.patch("/api/library/maths 2023.pdf", json={"role": "notes"}).status_code == 200
    job = c.post("/api/generate", json={"structure": "custom", "topic": "Algebra",
                                        "plan": [{"type": "mcq", "count": 3, "marks": 1}]}).get_json()
    job = _wait(c, job["id"])
    assert job["state"] == "done", job
    exam2 = c.get(f"/api/exams/{job['exam_id']}").get_json()
    assert [q["type"] for q in exam2["questions"]] == ["mcq"] * 3
    assert any(m.startswith("Reading maths 2023.pdf") for m in job["log"])

    assert c.delete(f"/api/exams/{exam['id']}").status_code == 200
    assert c.delete("/api/library/maths 2023.pdf").status_code == 200
    assert c.get("/api/library").get_json() == []


def test_api_keys_are_saved_masked(tmp_path, fake_ai):
    app = create_app(tmp_path / "p", tmp_path / "o", fake_ai[0])
    c = app.test_client()
    r = c.post("/api/providers/openai", json={"api_key": "sk-abcdefghijklmnop1234"}).get_json()
    assert r["key"] == "sk-…1234"
    openai = next(p for p in c.get("/api/meta").get_json()["providers"] if p["id"] == "openai")
    assert openai["key"] == "sk-…1234" and "abcdefgh" not in str(openai)
    assert c.post("/api/search-settings", json={"engine": "brave", "api_key": "brave-key-123456"}).status_code == 200
    assert c.get("/api/meta").get_json()["search"]["engine"] == "brave"


def test_rejects_unsafe_names(tmp_path, fake_ai):
    app = create_app(tmp_path / "p", tmp_path / "o", fake_ai[0])
    c = app.test_client()
    r = c.post("/api/library", data={"files": (io.BytesIO(b"x"), "../../evil.txt")})
    assert r.get_json() == {"saved": ["evil.txt"]}
    assert (tmp_path / "p" / "evil.txt").exists()
    assert c.post("/api/library", data={"files": (io.BytesIO(b"x"), "run.sh")}).status_code == 400
    assert c.get("/api/exams/..%2Fsecret").status_code == 404


def test_reports_ollama_offline(tmp_path):
    app = create_app(tmp_path / "p", tmp_path / "o", "http://127.0.0.1:9")
    status = app.test_client().get("/api/status?provider=ollama").get_json()
    assert status["ok"] is False and "Cannot reach Ollama" in status["error"]


def test_missing_cloud_key_is_reported(tmp_path):
    app = create_app(tmp_path / "p", tmp_path / "o")
    status = app.test_client().get("/api/status?provider=openai").get_json()
    assert status["ok"] is False and "No API key for OpenAI" in status["error"]


def test_generation_error_is_reported(sample_pdf, fake_ai, tmp_path):
    app = create_app(sample_pdf, tmp_path / "o", fake_ai[0])
    c = app.test_client()
    job = c.post("/api/generate", json={"model": "missing:1b", "structure": "match"}).get_json()
    job = _wait(c, job["id"])
    assert job["state"] == "error" and "ollama pull missing:1b" in job["error"]


def test_analysis_is_cached_and_reused(sample_pdf, fake_ai, tmp_path):
    host, server = fake_ai
    app = create_app(sample_pdf, tmp_path / "out", host)
    c = app.test_client()
    assert c.get("/api/analysis").get_json() == {"papers": ["maths_2023.pdf"], "analysis": None}

    job = _wait(c, c.post("/api/analyse", json={}).get_json()["id"])
    assert job["state"] == "done", job
    merged = job["result"]["merged"]
    assert merged["difficulty"] == {"easy": 50, "medium": 25, "hard": 25}
    assert merged["command_words"] == ["Solve", "Find"]
    assert merged["topic_counts"] == {"algebra": 1, "area": 1}
    assert c.get("/api/analysis").get_json()["analysis"]["merged"]["subject"] == "Mathematics"

    calls = len(server.requests)
    job = _wait(c, c.post("/api/generate", json={"structure": "match", "difficulty": "past",
                                                 "challenge": 2}).get_json()["id"])
    assert job["state"] == "done", job
    assert "Using the saved analysis of your past papers" in job["log"]
    new_calls = server.requests[calls:]
    assert not any("analyse past exam papers" in r["messages"][0]["content"] for r in new_calls)
    writer = next(r for r in new_calls if "brand-new" in r["messages"][0]["content"])
    prompt = writer["messages"][1]["content"]
    assert "Difficulty of each question, in order: easy, easy, medium, hard" in prompt
    assert "much harder than usual" in prompt and "Q4 needs two steps." in prompt
    exam = c.get(f"/api/exams/{job['exam_id']}").get_json()
    assert [q["difficulty"] for q in exam["questions"]] == ["easy", "easy", "medium", "hard"]
    assert exam["difficulty_mix"] == {"easy": 50, "medium": 25, "hard": 25}


def test_question_bank(sample_pdf, fake_ai, tmp_path):
    host, _ = fake_ai
    c = create_app(sample_pdf, tmp_path / "out", host).test_client()
    assert c.get("/api/bank").get_json()["bank"] is None
    job = _wait(c, c.post("/api/bank/build", json={}).get_json()["id"])
    assert job["state"] == "done", job
    bank = c.get("/api/bank").get_json()["bank"]
    assert bank["chapters"] == ["Algebra", "Geometry"]
    by_chapter = {q["number"]: q["chapter"] for q in bank["questions"]}
    assert by_chapter == {"1": "Algebra", "2": "Algebra", "3": "Algebra", "4": "Geometry"}
    assert bank["questions"][2]["difficulty"] == 9

    r = c.get("/api/bank/export?view=hardest&n=2&format=md")
    text = r.data.decode()
    assert "## Algebra" in text and "difficulty 9/10" in text
    assert text.index("Q3") < text.index("Q2") and "— Q1 " not in text  # top 2: hardest, then most marks
    assert "Why it's hard: needs two steps" in text
    assert c.get("/api/bank/export?view=chapters&format=docx").data[:2] == b"PK"

    job = _wait(c, c.post("/api/bank/solve", json={"ids": ["p1-q3"]}).get_json()["id"])
    assert job["state"] == "done", job
    q3 = next(q for q in job["result"]["questions"] if q["id"] == "p1-q3")
    assert q3["answer"] and q3["check"] in ("verified", "corrected")


def test_question_bank_pictures_reach_a_vision_model(sample_pdf, fake_ai, tmp_path):
    host, server = fake_ai
    server.vision = True
    c = create_app(sample_pdf, tmp_path / "out", host).test_client()
    job = _wait(c, c.post("/api/bank/build", json={}).get_json()["id"])
    assert job["state"] == "done", job
    questions = c.get("/api/bank").get_json()["bank"]["questions"]
    assert all(q.get("image") for q in questions), questions
    r = c.get(f"/api/bank/image/{questions[0]['image']}")
    assert r.status_code == 200 and r.data[:4] == b"\x89PNG"
    assert c.get("/api/bank/image/..%2Fsecret.png").status_code == 404

    sorting = [r for r in server.requests if "sorting past exam questions" in r["messages"][0]["content"]]
    assert sorting and len(sorting[0]["messages"][1]["images"]) == len(questions)
    assert "picture 1 = the question with id" in sorting[0]["messages"][1]["content"]

    job = _wait(c, c.post("/api/bank/solve", json={"ids": [questions[1]["id"]]}).get_json()["id"])
    assert job["state"] == "done", job
    solving = [r for r in server.requests if r["messages"][0]["content"].startswith("You are a senior examiner")]
    assert solving and len(solving[-1]["messages"][1]["images"]) == 1

    import io

    import docx
    data = c.get("/api/bank/export?view=chapters&format=docx").data
    assert len(docx.Document(io.BytesIO(data)).inline_shapes) == len(questions)


def test_text_only_model_gets_no_pictures(sample_pdf, fake_ai, tmp_path):
    host, server = fake_ai
    c = create_app(sample_pdf, tmp_path / "out", host).test_client()
    assert _wait(c, c.post("/api/bank/build", json={}).get_json()["id"])["state"] == "done"
    assert not any("images" in m for r in server.requests for m in r["messages"])


def test_each_file_has_its_own_language(tmp_path, fake_ai):
    host, server = fake_ai
    lib = tmp_path / "lib"
    lib.mkdir()
    (lib / "nota.txt").write_text("Fotosintesis ialah proses yang berlaku dalam daun. " * 20, encoding="utf-8")
    (lib / "笔记.txt").write_text("光合作用是植物利用光能制造葡萄糖的过程。" * 20, encoding="utf-8")
    (lib / "notes.txt").write_text("Photosynthesis is the process that happens in the leaf. " * 20)
    c = create_app(lib, tmp_path / "out", host).test_client()
    files = {f["name"]: f for f in c.get("/api/library").get_json()}
    assert files["nota.txt"]["detected"] == ["ms"] and files["笔记.txt"]["detected"] == ["zh"]
    assert files["notes.txt"]["detected"] == ["en"] and files["notes.txt"]["language"] == "auto"

    c.patch("/api/library/notes.txt", json={"language": "ms"})  # the user knows better
    assert {f["name"]: f for f in c.get("/api/library").get_json()}["notes.txt"]["language"] == "ms"

    job = _wait(c, c.post("/api/generate", json={"topic": "Photosynthesis", "language": "en",
                                                  "structure": "custom", "plan": [{"type": "short", "count": 1}],
                                                  "sources": {"use_files": True}}).get_json()["id"])
    assert job["state"] == "done", job
    readers = [r["messages"][0]["content"] for r in server.requests if "study notes" in r["messages"][0]["content"]]
    assert any("Some of the material is in Simplified Chinese" in r for r in readers)
    assert any("Some of the material is in Malay" in r for r in readers)
    writer = next(r for r in server.requests if "brand-new" in r["messages"][0]["content"])
    rule = writer["messages"][0]["content"]
    assert "in English, even when" in rule and "Malay" in rule and "Chinese" in rule
