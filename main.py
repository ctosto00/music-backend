"""
Backend music-proxy per Satin Echo.
"""

import base64
import os
import tempfile
import time

import requests
import yt_dlp
from flask import Flask, Response, request

app = Flask(__name__)

URL_CACHE: dict[str, dict] = {}
CACHE_TTL_SEC = 60 * 60

MEDIA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

def cookie_header_to_netscape(cookie_header: str) -> str:
    lines = ["# Netscape HTTP Cookie File"]
    for pair in cookie_header.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        name, _, value = pair.partition("=")
        name, value = name.strip(), value.strip()
        lines.append(
            f".youtube.com\tTRUE\t/\tTRUE\t9999999999\t{name}\t{value}"
        )
    return "\n".join(lines) + "\n"

def get_stream_url(video_id, cookie_header):
    cached = URL_CACHE.get(video_id)
    if cached and cached["expires"] > time.time():
        return cached["url"]

    ydl_opts = {
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

    cookie_path = None
    if cookie_header:
        netscape = cookie_header_to_netscape(cookie_header)
        fd, cookie_path = tempfile.mkstemp(suffix=".txt", prefix="ytc_")
        with os.fdopen(fd, "w") as f:
            f.write(netscape)
        ydl_opts["cookiefile"] = cookie_path

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}",
                download=False,
            )
            url = info.get("url") if info else None
            if not url:
                return None
            URL_CACHE[video_id] = {
                "url": url,
                "expires": time.time() + CACHE_TTL_SEC,
            }
            return url
    except Exception as err:
        app.logger.error("yt-dlp error for %s: %s", video_id, err)
        return None
    finally:
        if cookie_path:
            try:
                os.unlink(cookie_path)
            except OSError:
                pass

@app.get("/")
def index():
    return (
        "music-backend\nUsage: /audio?videoId=<YOUTUBE_VIDEO_ID>\n",
        200,
        {"Content-Type": "text/plain"},
    )

@app.get("/health")
def health():
    return "ok", 200, {"Content-Type": "text/plain"}

@app.get("/audio")
def audio():
    video_id = request.args.get("videoId")
    if not video_id:
        return "missing videoId param", 400

    cookie_header = None
    cookie_b64 = request.headers.get("X-YT-Cookie-B64")
    if cookie_b64:
        try:
            cookie_header = base64.b64decode(cookie_b64).decode("utf-8")
        except Exception:
            app.logger.warning("X-YT-Cookie-B64 non decodificabile")

    stream_url = get_stream_url(video_id, cookie_header)
    if not stream_url:
        return "failed to resolve stream", 502

    upstream_headers = {
        "User-Agent": MEDIA_UA,
        "Range": request.headers.get("Range", "bytes=0-"),
    }

    try:
        upstream = requests.get(
            stream_url, headers=upstream_headers, stream=True, timeout=30
        )
    except requests.RequestException as err:
        app.logger.error("upstream fetch failed: %s", err)
        return f"upstream fetch failed: {err}", 502

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=16384):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    response_headers = {
        "Content-Type": upstream.headers.get("Content-Type", "audio/mp4"),
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
    }
    if "Content-Length" in upstream.headers:
        response_headers["Content-Length"] = upstream.headers["Content-Length"]

    return Response(
        generate(),
        status=upstream.status_code,
        headers=response_headers,
    )
