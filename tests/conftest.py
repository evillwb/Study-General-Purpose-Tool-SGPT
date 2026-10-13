import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pymupdf
import pytest

SAMPLE_PAGES = [
    "Mathematics Paper 1 (Higher)\nTime allowed: 90 minutes\nAnswer all questions.\n\n"
    "1. Solve 3x + 5 = 20. [2 marks]\n\n"
    "2. A shop sells pens at 40p each.\n(a) Find the cost of 7 pens. [1]\n"
    "(b) How many pens can be bought for 5 pounds? [2]\nPage 1 of 2",
    "Question 3\nExpand and simplify (x + 3)(x - 2).\nList your steps:\n1. Expand\n"
    "2. Collect like terms [3 marks]\n\n"
    "4. Find the area of a circle of radius 4 cm. [3 marks]\nPage 2 of 2",
]


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never read or write the real ~/.sgpt config or API keys during tests."""
    monkeypatch.setenv("SGPT_CONFIG", str(tmp_path / "config.json"))
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY",
                "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "CUSTOM_API_KEY", "OLLAMA_HOST",
                "BRAVE_API_KEY", "TAVILY_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def sample_pdf(tmp_path):
    folder = tmp_path / "library"
    folder.mkdir()
    doc = pymupdf.open()
    for text in SAMPLE_PAGES:
        doc.new_page().insert_text((50, 72), text, fontsize=11)
    doc.save(folder / "maths_2023.pdf")
    return folder


def fake_reply(system: str, prompt: str) -> str:
    """What the fake model answers, chosen from the prompt."""
    if "analyse past exam papers" in system:
        return json.dumps({
            "subject": "Mathematics", "level": "GCSE", "duration_minutes": 90, "total_marks": 11,
            "instructions": ["Answer all questions."],
            "sections": [{"name": "Section A", "question_count": 4, "marks": 11,
                          "question_types": ["short answer"], "topics": ["algebra", "area"]}],
            "topics": ["algebra", "area"], "style_notes": "short direct questions",
            "difficulty": {"easy": 2, "medium": 1, "hard": 1},
            "difficulty_notes": "Q4 needs two steps.", "command_words": ["solve", "Find"]})
    if "study notes" in system:
        return "- Plants make glucose by photosynthesis.\n- It needs light and chlorophyll."
    if "brand-new" in system:
        count = int(re.search(r"Write (\d+) new exam", prompt).group(1))
        mcq = "Multiple choice" in prompt
        return "<think>plan</think>" + json.dumps({"questions": [
            {"type": "mcq" if mcq else "short", "topic": "algebra", "difficulty": "easy",
             "marks": 1 if mcq else 3, "question": f"Solve 2x + {i} = 9 for x.",
             "options": ["A. 1", "B) 2", "3.5", "4"] if mcq else [], "parts": []}
            for i in range(1, count + 1)]})
    if "strict independent examiner checking test items" in system:
        items = json.loads(prompt.split("ITEMS:\n", 1)[1])
        # Pretend item 1's key was wrong and item 2 is broken.
        return json.dumps({"checks": [
            {"n": it["n"], "ok": it["n"] != 2,
             "answer": (1 if isinstance(it.get("answer"), int) else "fixed") if it["n"] == 1 else it.get("answer")}
            for it in items]})
    if "expert teacher" in system or "exam study guides" in system:
        n = int((re.search(r"(?:Make|Write) (\d+)", prompt) or re.search(r"Tulis (\d+)", prompt) or [0, 3])[1])
        if "flashcards" in prompt:
            return json.dumps({"cards": [{"front": f"Term {i}", "back": f"Meaning {i}"} for i in range(n)]})
        if "multiple-choice" in prompt:
            return json.dumps({"questions": [{"question": f"Q{i}?", "options": ["a", "b", "c", "d"],
                                              "answer": 2, "explanation": "because"} for i in range(n)]})
        if "TENSES" in prompt or "WORD FORM" in prompt:
            return json.dumps({"items": [{"sentence": f"She _____ (go) home {i}.", "base": "go",
                                          "answer": "went", "explanation": "past"} for i in range(n)]})
        if "KENAL PASTI" in prompt:
            return json.dumps({"items": [{"segments": ["Para pelajar", "sedang", "pelajaran-pelajaran", "itu."],
                                          "error_index": 2, "correction": "pelajaran", "explanation": "jamak"}
                                         for _ in range(n)]})
        if prompt.startswith("Explain"):
            words = re.search(r"these words: (.*?)\. Level", prompt)
            names = words.group(1).split(", ") if words else ["photosynthesis", "chlorophyll"]
            return json.dumps({"words": [{"word": w, "part_of_speech": "noun", "meaning": f"meaning of {w}",
                                          "example": f"I like {w}.", "translation": "翻译", "synonyms": ["x"]}
                                         for w in names]})
        if "List the chapters" in prompt:
            return json.dumps({"chapters": ["Algebra", "Geometry"]})
        if "memorise" in prompt:
            return "### Formulas\n- a² + b² = c²"
        if "study-guide section" in prompt:
            chapter = re.search(r"chapter \d+: (.*?) \(", prompt).group(1)
            return f"> key fact about {chapter}\n> second fact\n\n- Trap: careless slips"
        if "Answer the student's question" in prompt:
            return "Chlorophyll absorbs **light**."
        return "# Photosynthesis\n\n## Key terms\n\n| Term | Definition | Example |\n|---|---|---|\n| Glucose | sugar | — |\n\n- Light → glucose"
    if "knows the syllabus" in system:
        return json.dumps({"chapters": ["Algebra", "Geometry"]})
    if "sorting past exam questions" in system:
        rows = []
        for qid, text in re.findall(r"\[id: ([^\]]+)\][^\n]*\n([^\n]*)", prompt):
            algebra = any(w in text for w in ("Solve", "Expand", "pens"))
            rows.append({"id": qid, "chapter": "Algebra" if algebra else "Geometry",
                         "topic": "equations" if algebra else "circles", "type": "short",
                         "difficulty": 9 if "Expand" in text else 4 if algebra else 6,
                         "reason": "needs two steps" if "Expand" in text else "routine"})
        return json.dumps({"questions": rows})
    if "independent senior examiner" in system:
        items = re.findall(r"^Question (\d+) \[.*?\n(.*)$", prompt, re.MULTILINE)
        checks = []
        for n, text in items:
            entry = {"number": int(n), "question_ok": True, "answer_ok": True, "problem": ""}
            if "2x + 3" in text:
                entry.update(question_ok=False, problem="two options are correct")
            elif "2x + 2" in text:
                entry.update(answer_ok=False, problem="arithmetic slip", answer="2x = 7, so x = 3.5",
                             final_answer="x = 3.5",
                             marking_points=[{"point": "x = 3.5", "marks": 3}])
            checks.append(entry)
        return json.dumps({"checks": checks})
    if "senior examiner" in system:
        numbers = [int(n) for n in re.findall(r"^Question (\d+) \[", prompt, re.MULTILINE)]
        return json.dumps({"solutions": [
            {"number": n, "answer": "Subtract, then divide.\nx = 4",
             "final_answer": "C 3.5" if "Multiple choice" in prompt else "x = 4",
             "marking_points": [{"point": "correct method", "marks": 1},
                                {"point": "x = 4", "marks": 2}],
             "accept": "4.0"} for n in numbers]})
    return "OK"


def _text_of(content) -> str:
    """The text of a message whose content may be a list of text and image parts."""
    if isinstance(content, list):
        return "\n".join(p.get("text", "") for p in content if p.get("type") == "text")
    return content


class _FakeAI(BaseHTTPRequestHandler):
    """Speaks just enough of the Ollama, OpenAI and Anthropic APIs for the tests."""
    requests: list = []
    reject_temperature = False
    vision = False  # whether the fake Ollama model says it can read images
    busy = 0  # answer this many chat requests with "503 high demand" first

    def log_message(self, *args):
        pass

    def _send(self, body, status=200, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/tags"):
            return self._send({"models": [{"name": "qwen3:4b"}]})
        if self.path.startswith("/v1/models"):
            if "anthropic-version" in self.headers:
                return self._send({"data": [{"id": "claude-opus-5-5", "type": "model",
                                             "display_name": "Claude Opus 5.5",
                                             "created_at": "2026-01-01T00:00:00Z"}],
                                   "has_more": False, "first_id": "claude-opus-5-5",
                                   "last_id": "claude-opus-5-5"})
            if self.headers.get("Authorization") != "Bearer good-key":
                return self._send({"error": {"message": "Invalid API key"}}, 401)
            return self._send({"data": [{"id": "gpt-test"}, {"id": "text-embedding-3"}]})
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path == "/api/show":
            return self._send({"capabilities": ["completion"] + (["vision"] if type(self).vision else [])})
        type(self).requests.append({"path": self.path, "headers": dict(self.headers), **payload})
        if self.path == "/api/chat":  # Ollama
            msgs = payload["messages"]
            reply = fake_reply(msgs[0]["content"], msgs[1]["content"])
            lines = [{"message": {"content": reply[i:i + 20]}, "done": False}
                     for i in range(0, len(reply), 20)] + [{"message": {"content": ""}, "done": True}]
            return self._send("\n".join(json.dumps(x) for x in lines).encode())
        if self.path == "/v1/chat/completions":  # OpenAI-compatible
            if type(self).busy > 0:
                type(self).busy -= 1
                return self._send({"error": {"code": 503, "status": "UNAVAILABLE", "message":
                                             "This model is currently experiencing high demand."}}, 503)
            if type(self).reject_temperature and "temperature" in payload:
                return self._send({"error": {"message": "Unsupported parameter: 'temperature'"}}, 400)
            msgs = payload["messages"]
            reply = fake_reply(msgs[0]["content"], _text_of(msgs[1]["content"]))
            events = [{"choices": [{"delta": {"content": reply[i:i + 20]}}]}
                      for i in range(0, len(reply), 20)]
            body = "".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n"
            return self._send(body.encode(), ctype="text/event-stream")
        if self.path.startswith("/v1/messages"):  # Anthropic
            reply = fake_reply(payload.get("system", ""), _text_of(payload["messages"][0]["content"]))
            events = [
                ("message_start", {"type": "message_start", "message": {
                    "id": "msg_1", "type": "message", "role": "assistant", "model": payload["model"],
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 5, "output_tokens": 1}}}),
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                *[("content_block_delta", {"type": "content_block_delta", "index": 0,
                                           "delta": {"type": "text_delta", "text": reply[i:i + 30]}})
                  for i in range(0, len(reply), 30)],
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta",
                                   "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                   "usage": {"output_tokens": 9}}),
                ("message_stop", {"type": "message_stop"}),
            ]
            body = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)
            return self._send(body.encode(), ctype="text/event-stream")
        self._send({"error": "not found"}, 404)


@pytest.fixture
def fake_ai():
    _FakeAI.requests = []
    _FakeAI.reject_temperature = False
    _FakeAI.vision = False
    _FakeAI.busy = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", _FakeAI
    server.shutdown()
