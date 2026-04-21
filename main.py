"""
Backend music-proxy per Satin Echo.
Risolve YouTube videoId → URL audio via yt-dlp e fa da relay HTTP.

Endpoint:
  GET  /                      usage hint
  GET  /health                healthcheck
  GET  /audio?videoId=<id>    streamma audio del video
"""

import os
import time

import requests
import yt_dlp
from flask import Flask, Response, request

app = Flask(__name__)

# Cache in-memory videoId → stream URL con TTL.
# Gli URL YouTube scadono dopo ~6h, un'ora di cache è conservativa.
URL_CACHE: dict[str, dict] = {}
CACHE_TTL_SEC = 60 * 60

# User-Agent per il download del media da googlevideo.com.
# Coerente con quello che yt-dlp usa di default per il WEB client.
MEDIA_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def get_stream_url(video_id: str) -> str | None:
    cached = URL_CACHE.get(video_id)
    if cached and cached["expires"] > time.time():
        return cached["url"]

    ydl_opts = {
        # Preferenza: audio m4a (compatibile con expo-audio su Android),
        # fallback al migliore audio disponibile
        "format": "bestaudio[ext=m4a]/bestaudio",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }

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
    except Exception as err:  # noqa: BLE001
        app.logger.error("yt-dlp error for %s: %s", video_id, err)
        return None


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

    stream_url = get_stream_url(video_id)
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
