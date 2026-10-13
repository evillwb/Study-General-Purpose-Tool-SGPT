import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import fitz
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


@pytest.fixture
def sample_pdf(tmp_path):
    folder = tmp_path / "papers"
    folder.mkdir()
    doc = fitz.open()
    for text in SAMPLE_PAGES:
        page = doc.new_page()
        page.insert_text((50, 72), text, fontsize=11)
    doc.save(folder / "maths_2023.pdf")
    return folder


class _FakeOllama(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def _send(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send(json.dumps({"models": [{"name": "qwen3:4b"}]}).encode())

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).requests.append(payload)
        if payload.get("format") == "json":
            reply = json.dumps({
                "subject": "Mathematics", "level": "GCSE", "duration_minutes": 90,
                "total_marks": 11, "instructions": ["Answer all questions."],
                "sections": [{"name": "Section A", "question_count": 4, "marks": 11,
                              "question_types": ["short answer"], "topics": ["algebra", "area"]}],
                "topics": ["algebra", "area"], "style_notes": "short direct questions",
            })
        elif "marking scheme" in payload["messages"][1]["content"]:
            reply = "<think>hidden</think>### Question 1\n**Answer**: x = 4"
        else:
            reply = "## Section A\n**Question 1**\nSolve 2x + 1 = 9. [2]"
        lines = [{"message": {"content": reply[i:i + 10]}, "done": False}
                 for i in range(0, len(reply), 10)]
        lines.append({"message": {"content": ""}, "done": True})
        self._send("\n".join(json.dumps(l) for l in lines).encode())


@pytest.fixture
def fake_ollama():
    _FakeOllama.requests = []
    server = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", _FakeOllama.requests
    server.shutdown()
