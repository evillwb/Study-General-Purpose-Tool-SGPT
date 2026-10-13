import functools
import subprocess
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from sgpt import media
from sgpt.app import create_app

pytestmark = pytest.mark.skipif(not (media.available() and media.ffmpeg()),
                                reason="yt-dlp / ffmpeg not installed")


@pytest.fixture(scope="module")
def video_server(tmp_path_factory):
    """A local web server with a 3-second test video (with sound) and a silent one."""
    root = tmp_path_factory.mktemp("srv")
    ff = media.ffmpeg()
    subprocess.run([ff, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=320x240:rate=10",
                    "-f", "lavfi", "-i", "sine=frequency=440", "-t", "3", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(root / "lesson.mp4")], check=True)
    subprocess.run([ff, "-loglevel", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
                    "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(root / "loop.mp4")], check=True)
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}", root
    server.shutdown()


def test_video_audio_and_mute(video_server, tmp_path):
    url = f"{video_server[0]}/lesson.mp4"
    steps = []
    got = media.download(url, {"mode": "auto"}, tmp_path / "a", progress=lambda f, m, i: steps.append(f))
    assert got["file"].name == "lesson.mp4" and got["file"].stat().st_size > 10000 and steps[-1] == 1.0
    mp3 = media.download(url, {"mode": "audio", "audio_format": "mp3", "bitrate": "64",
                               "filename": "nerdy"}, tmp_path / "b")["file"]
    assert mp3.suffix == ".mp3" and mp3.read_bytes()[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3")
    assert "(generic, lesson)" in mp3.name
    with pytest.raises(InterruptedError):
        media.download(url, {}, tmp_path / "c", should_stop=lambda: True)


def test_settings_and_formats():
    s = media.settings({"quality": "720", "codec": "vp9", "dub": "ms", "container": "zip", "cookies": "x"})
    assert s["container"] == "auto" and s["cookies"] == "none"  # invalid values fall back
    f = media.format_selector(s)
    assert f.startswith("bv*[height<=720][vcodec~='^vp0?9']+ba[language^=ms]") and f.endswith("/b")
    assert "[vcodec!^=hev]" in f and "[vcodec!^=hev]" not in media.format_selector({**s, "allow_h265": True})
    assert media.format_selector(media.settings({"mode": "audio"})) == "ba/b"
    assert media.options(s, media.Path("/tmp"))["merge_output_format"] == "webm"
    assert media.options(media.settings({"cookies": "firefox"}), media.Path("/tmp"))["cookiesfrombrowser"] == ("firefox",)
    name = media.file_name(media.settings({"filename": "pretty"}),
                           {"title": "Cells: the basics?", "height": 1080, "vcodec": "av01.0.08M",
                            "extractor_key": "Youtube", "id": "x1"}, "webm")
    assert name == "Cells_ the basics (1080p, av1, youtube).webm"


def test_subtitles_to_text_and_gif(video_server, tmp_path):
    vtt = ("WEBVTT\nKind: captions\nLanguage: en\n\n00:00:00.000 --> 00:00:02.000\nPlants make <c>food</c>\n\n"
           "00:00:02.000 --> 00:00:04.000\nPlants make food\nusing light\n")
    assert media.vtt_to_text(vtt) == "Plants make food using light"
    clip = tmp_path / "loop.mp4"
    clip.write_bytes((video_server[1] / "loop.mp4").read_bytes())
    gif = media.to_gif(clip)
    assert gif.read_bytes()[:6] == b"GIF89a" and not clip.exists()
    assert media._looping_twitter_video({"extractor_key": "Twitter", "acodec": "none", "duration": 4})
    assert not media._looping_twitter_video({"extractor_key": "Youtube", "acodec": "none", "duration": 4})


def _wait(c, job_id):
    for _ in range(300):
        job = c.get(f"/api/jobs/{job_id}").get_json()
        if job["state"] != "running":
            return job
        time.sleep(0.05)
    raise AssertionError("job did not finish")


def test_download_endpoints(video_server, tmp_path):
    c = create_app(tmp_path / "lib", tmp_path / "out").test_client()
    assert c.get("/api/meta").get_json()["media"]["available"]
    assert c.post("/api/media/download", json={"url": "file:///etc/passwd"}).status_code == 400
    job = _wait(c, c.post("/api/media/download", json={"url": f"{video_server[0]}/lesson.mp4",
                                                        "settings": {"mode": "audio"}}).get_json()["id"])
    assert job["state"] == "done", job
    assert job["result"]["meta"]["title"] == "lesson"
    file = job["result"]["file"]
    assert file["name"] == "lesson.mp3" and c.get(file["url"]).data[:3] in (b"ID3", b"\xff\xfb", b"\xff\xf3")
    assert [f["name"] for f in c.get("/api/downloads").get_json()] == ["lesson.mp3"]
    assert c.get(f"/api/downloads/{file['job']}/../../x").status_code == 404
    assert c.delete(file["url"]).get_json()["ok"] and c.get("/api/downloads").get_json() == []
    _wait(c, c.post("/api/media/download", json={"url": f"{video_server[0]}/lesson.mp4"}).get_json()["id"])
    assert c.delete("/api/downloads").get_json()["removed"] == 1

    job = _wait(c, c.post("/api/media/transcript", json={"url": f"{video_server[0]}/lesson.mp4"}).get_json()["id"])
    assert job["state"] == "error" and "no subtitles" in job["error"]
