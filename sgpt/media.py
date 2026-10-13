"""Download videos and audio from YouTube and other sites (yt-dlp), cobalt-style.

Settings mirror cobalt.tools: video quality, preferred YouTube codec, container, audio
format and bitrate, dub and subtitle language, filename style and file metadata.
ffmpeg (bundled through imageio-ffmpeg) merges video and audio and converts formats.

Only download videos you own or have permission to save; respect each site's terms.
"""

from __future__ import annotations

import re
from pathlib import Path

QUALITIES = ["max", "2160", "1440", "1080", "720", "480", "360", "240", "144"]
QUALITY_LABELS = {"max": "8k+", "2160": "4k", "1440": "1440p", "1080": "1080p", "720": "720p",
                  "480": "480p", "360": "360p", "240": "240p", "144": "144p"}
CODECS = {"h264": "avc1", "av1": "av01", "vp9": "vp0?9"}
CONTAINERS = ["auto", "mp4", "webm", "mkv"]
AUDIO_FORMATS = ["best", "mp3", "ogg", "wav", "opus"]
BITRATES = ["320", "256", "128", "96", "64", "8"]
FILENAME_STYLES = ["classic", "basic", "pretty", "nerdy"]
MODES = ["auto", "audio", "mute"]
BROWSERS = ["none", "chrome", "edge", "firefox", "brave", "opera", "vivaldi", "safari"]

# The services cobalt lists; yt-dlp supports all of them (and many more).
SITES = ["YouTube", "TikTok", "Instagram", "Facebook", "X (Twitter)", "Reddit", "Bilibili", "Vimeo",
         "SoundCloud", "Twitch clips", "Pinterest", "Tumblr", "Dailymotion", "Bluesky", "Snapchat",
         "Streamable", "VK", "OK.ru", "Rutube", "Loom", "Xiaohongshu (RedNote)", "Newgrounds"]

DEFAULTS = {"mode": "auto", "quality": "1080", "codec": "h264", "container": "auto",
            "audio_format": "mp3", "bitrate": "128", "dub": "original", "subtitles": "none",
            "filename": "basic", "no_metadata": False, "allow_h265": False, "twitter_gif": True,
            "cookies": "none"}

_AUDIO_CODEC = {"mp3": "mp3", "ogg": "vorbis", "wav": "wav", "opus": "opus"}


class MediaError(RuntimeError):
    pass


def available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def ffmpeg() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        import shutil
        return shutil.which("ffmpeg")


def settings(raw: dict | None) -> dict:
    """Known settings only, with defaults for anything missing or invalid."""
    raw = raw or {}
    s = dict(DEFAULTS)
    for key, allowed in (("mode", MODES), ("quality", QUALITIES), ("codec", list(CODECS)),
                         ("container", CONTAINERS), ("audio_format", AUDIO_FORMATS),
                         ("bitrate", BITRATES), ("filename", FILENAME_STYLES), ("cookies", BROWSERS)):
        if str(raw.get(key)) in allowed:
            s[key] = str(raw[key])
    for key in ("dub", "subtitles"):
        value = str(raw.get(key) or s[key])
        if re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,4})?|original|none|auto", value):
            s[key] = value
    for key in ("no_metadata", "allow_h265", "twitter_gif"):
        if key in raw:
            s[key] = bool(raw[key])
    return s


def format_selector(s: dict) -> str:
    """yt-dlp format string for the settings: best match first, then fall back."""
    height = "" if s["quality"] == "max" else f"[height<={s['quality']}]"
    codec = f"[vcodec~='^{CODECS[s['codec']]}']"
    # Without "allow h265", HEVC is avoided (many players can't open it) unless it's all there is.
    no_hevc = "" if s["allow_h265"] else "[vcodec!^=hev][vcodec!^=hvc]"
    lang = f"[language^={s['dub']}]" if s["dub"] not in ("original", "auto") else ""
    m4a = "[ext=m4a]" if s["container"] == "mp4" or (s["container"] == "auto" and s["codec"] == "h264") else ""
    if s["mode"] == "audio":
        return "/".join(dict.fromkeys(x for x in (f"ba{lang}", "ba", "b") if x))
    if s["mode"] == "mute":
        return f"bv*{height}{codec}/bv*{height}{no_hevc}/bv*{height}/bv*/b{height}/b"
    audio = [f"ba{lang}{m4a}", f"ba{lang}", f"ba{m4a}", "ba"]
    tries = [f"bv*{height}{codec}+{a}" for a in dict.fromkeys(audio)]
    tries += [f"bv*{height}{no_hevc}+ba", f"b{height}{no_hevc}", f"bv*{height}+ba", f"b{height}", "bv*+ba", "b"]
    return "/".join(dict.fromkeys(tries))


def _container(s: dict) -> str:
    if s["container"] != "auto":
        return s["container"]
    return "mp4" if s["codec"] == "h264" else "webm"


def _codec_name(vcodec: str | None) -> str:
    v = (vcodec or "").lower()
    for prefix, name in (("avc", "h264"), ("av01", "av1"), ("vp09", "vp9"), ("vp9", "vp9"), ("hev", "h265"),
                         ("hvc", "h265")):
        if v.startswith(prefix):
            return name
    return ""


def file_name(s: dict, d: dict, ext: str) -> str:
    """Name for the saved file, in cobalt's filename styles (unknown details are left out)."""
    def clean(text: str) -> str:  # characters Windows doesn't allow in file names
        return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text or "").strip(" ._")

    title = clean(d.get("title") or "") or "video"
    uploader = clean(d.get("uploader") or "")
    site = (d.get("extractor_key") or d.get("extractor") or "web").lower()
    vid = d.get("id") or ""
    if s["mode"] == "audio":
        base = f"{uploader} - {title}" if uploader else title
        name = {"classic": f"{site}_{vid}_audio", "basic": base, "pretty": f"{base} ({site})",
                "nerdy": f"{base} ({site}, {vid})"}[s["filename"]]
    else:
        height, width = d.get("height"), d.get("width")
        codec = _codec_name(d.get("vcodec"))
        details = [x for x in (f"{height}p" if height else "", codec) if x]
        extra = {"classic": [], "basic": [], "pretty": [site], "nerdy": [site, vid]}[s["filename"]]
        if s["filename"] == "classic":
            name = "_".join(x for x in (site, vid, f"{width}x{height}" if height else "", codec) if x)
        else:
            inside = ", ".join(details + [x for x in extra if x])
            name = f"{title} ({inside})" if inside else title
        if s["mode"] == "mute":
            name += " (mute)"
    name = clean(name)[:150] or "download"
    return f"{name}.{ext}"


def options(s: dict, out_dir: Path, hook=None) -> dict:
    """yt-dlp options for the settings."""
    opts = {
        "format": format_selector(s),
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),  # renamed afterwards (file_name)
        "restrictfilenames": False,
        "windowsfilenames": True,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "progress_hooks": [hook] if hook else [],
        "postprocessors": [],
        "concurrent_fragment_downloads": 4,
    }
    if ffmpeg():
        opts["ffmpeg_location"] = ffmpeg()
    if s["cookies"] != "none":
        # For videos that need you to be signed in: read the cookies of your own browser.
        opts["cookiesfrombrowser"] = (s["cookies"],)
    if s["mode"] == "audio":
        if s["audio_format"] != "best":
            opts["postprocessors"].append({"key": "FFmpegExtractAudio",
                                           "preferredcodec": _AUDIO_CODEC[s["audio_format"]],
                                           "preferredquality": s["bitrate"]})
    else:
        opts["merge_output_format"] = _container(s)
        if s["subtitles"] != "none":
            opts.update(writesubtitles=True, writeautomaticsub=True,
                        subtitleslangs=[s["subtitles"] + ".*", s["subtitles"]] if s["subtitles"] != "auto" else ["all"])
            opts["postprocessors"].append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
    if not s["no_metadata"]:
        opts["postprocessors"].append({"key": "FFmpegMetadata", "add_metadata": True})
    return opts


def info(url: str) -> dict:
    """Title, length, thumbnail and what is available, without downloading."""
    import yt_dlp

    try:
        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "noplaylist": True,
                               "skip_download": True}) as ydl:
            data = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        raise MediaError(_clean_error(exc)) from None
    heights = sorted({f.get("height") for f in data.get("formats") or [] if f.get("height")}, reverse=True)
    return {"title": data.get("title") or "", "uploader": data.get("uploader") or "",
            "duration": data.get("duration"), "thumbnail": data.get("thumbnail") or "",
            "site": data.get("extractor_key") or "", "heights": heights,
            "subtitles": sorted(set(data.get("subtitles") or {}) | set(data.get("automatic_captions") or {}))}


def _clean_error(exc: Exception) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).replace("ERROR: ", "").strip()
    if "Sign in to confirm" in text or "confirm you" in text or "login" in text.lower() \
            or "log in" in text.lower():
        text += (" This site wants you to be signed in: choose your browser under "
                 "Download settings → other → sign-in cookies, and sign in to the site in that browser.")
    if "Unsupported URL" in text:
        text = "This link isn't supported. Paste the link of a single video or post."
    return text


def download(url: str, raw_settings: dict, out_dir: Path, *, progress=None, should_stop=None) -> dict:
    """Download url into out_dir. progress(fraction, message, info) is called as it goes.

    Returns {"file": Path, "title", "uploader", "duration", "thumbnail", "site"}.
    """
    import yt_dlp

    s = settings(raw_settings)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {}

    def hook(d):
        if should_stop and should_stop():
            raise yt_dlp.utils.DownloadCancelled("Stopped")
        if not progress:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            speed = d.get("speed")
            message = "Downloading" + (f" · {_size(done)} of {_size(total)}" if total else f" · {_size(done)}") \
                + (f" · {_size(speed)}/s" if speed else "")
            progress(done / total if total else 0, message, meta)
        elif d.get("status") == "finished":
            progress(1.0, "Processing (merging and converting)…", meta)

    opts = options(s, out_dir, hook)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=False)
            meta.update(title=data.get("title") or "", uploader=data.get("uploader") or "",
                        duration=data.get("duration"), thumbnail=data.get("thumbnail") or "",
                        site=data.get("extractor_key") or "")
            if progress:
                progress(0, "Starting the download…", meta)
            data = ydl.process_ie_result(data, download=True)
    except yt_dlp.utils.DownloadCancelled:
        raise InterruptedError() from None
    except yt_dlp.utils.DownloadError as exc:
        raise MediaError(_clean_error(exc)) from None
    except Exception as exc:  # e.g. the browser's cookie store could not be read
        if s["cookies"] != "none" and "cookie" in str(exc).lower():
            raise MediaError(f"Could not read {s['cookies']}'s cookies ({exc}). Close the browser and try "
                             "again, or choose another browser (Firefox works best).") from None
        raise
    files = [p for p in out_dir.iterdir() if p.is_file() and p.suffix not in (".part", ".ytdl", ".vtt", ".srt")]
    if not files:
        raise MediaError("Nothing was downloaded.")
    newest = max(files, key=lambda p: p.stat().st_mtime)
    if s["twitter_gif"] and s["mode"] != "audio" and _looping_twitter_video(data):
        if progress:
            progress(1.0, "Converting to GIF…", meta)
        newest = to_gif(newest)
    final = out_dir / file_name(s, data, newest.suffix.lstrip("."))
    if final != newest:
        final = newest.replace(final)
    return {"file": final, **meta}


def _looping_twitter_video(data: dict) -> bool:
    """X/Twitter "GIFs" are short silent looping videos."""
    site = (data.get("extractor_key") or data.get("extractor") or "").lower()
    return site.startswith("twitter") and (data.get("acodec") in (None, "none")) \
        and (data.get("duration") or 0) <= 60


def to_gif(video: Path) -> Path:
    """Convert a short video to a GIF with a proper palette (as cobalt does for X/Twitter)."""
    import subprocess

    gif = video.with_suffix(".gif")
    cmd = [ffmpeg() or "ffmpeg", "-loglevel", "error", "-y", "-i", str(video), "-vf",
           "fps=15,scale='min(480,iw)':-1:flags=lanczos,split[a][b];[a]palettegen[p];[b][p]paletteuse",
           "-loop", "0", str(gif)]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
    except (subprocess.SubprocessError, OSError) as exc:
        raise MediaError(f"Could not convert to GIF: {exc}") from None
    video.unlink(missing_ok=True)
    return gif


def transcript(url: str, language: str = "en") -> tuple[str, str]:
    """(title, plain text of the subtitles) for using a video as a study source."""
    import tempfile

    import yt_dlp

    with tempfile.TemporaryDirectory() as tmp:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True,
                "writesubtitles": True, "writeautomaticsub": True, "subtitlesformat": "vtt",
                "subtitleslangs": [f"{language}.*", language, "en.*", "en", "zh.*", "ms.*"],
                "outtmpl": str(Path(tmp) / "sub.%(ext)s")}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                data = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as exc:
            raise MediaError(_clean_error(exc)) from None
        subs = sorted(Path(tmp).glob("*.vtt"))
        if not subs:
            raise MediaError("This video has no subtitles or captions to use.")
        best = next((p for p in subs if f".{language}" in p.name), subs[0])
        return data.get("title") or "Video", vtt_to_text(best.read_text(encoding="utf-8", errors="replace"))


def vtt_to_text(vtt: str) -> str:
    """Subtitle file -> readable text: no timings, tags or the repeated lines of auto-captions."""
    lines, last = [], ""
    for line in vtt.splitlines():
        line = re.sub(r"<[^>]+>", "", line).strip()
        if (not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE"))
                or line.isdigit() or line == last):
            continue
        lines.append(line)
        last = line
    text = " ".join(lines)
    return re.sub(r"\s+", " ", text).strip()


def _size(n) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
