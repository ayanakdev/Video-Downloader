"""Single-video extraction and conversion, isolated from the Streamlit interface."""
from pathlib import Path
from urllib.parse import urlparse
import os
import shutil

import imageio_ffmpeg
import yt_dlp

PLATFORMS = {"YouTube": ("youtube.com", "youtu.be"), "Instagram": ("instagram.com",), "TikTok": ("tiktok.com",)}
MAX_BYTES = 250 * 1024 * 1024


class MediaError(Exception):
    pass


def validate_url(value, platform):
    value = value.strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.port not in (None, 80, 443):
        raise MediaError("Paste a full https:// video link from your selected platform.")
    if not any(host == domain or host.endswith("." + domain) for domain in PLATFORMS[platform]):
        raise MediaError(f"That link does not belong to {platform}. Choose the matching platform and try again.")
    if not parsed.path.strip("/"):
        raise MediaError("Paste a link to a specific video, rather than a profile or homepage.")
    return value


def options():
    return {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "socket_timeout": 25, "retries": 2, "extractor_retries": 2,
        "max_filesize": MAX_BYTES, "cachedir": False,
        "ffmpeg_location": shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe(),
        "restrictfilenames": True,
        "js_runtimes": {"deno": {}, "node": {}},
    }


def friendly_error(error):
    message = str(error).lower()
    if any(word in message for word in ("winerror 10013", "permission denied", "operation not permitted")):
        return ("The app's internet access is blocked by its launch environment or firewall. "
                "Restart GetVideo using start.bat from the project folder in a normal Windows session. "
                "Deployment is not required. This affects every platform and both MP4 and MP3.")
    if any(word in message for word in ("timed out", "name resolution", "getaddrinfo", "failed to establish a new connection", "couldn't connect", "could not resolve")):
        return "The app cannot connect to the platform. Check this computer's internet connection and try again."
    if "429" in message or "too many requests" in message or "rate-limit" in message:
        return "The platform is temporarily limiting requests from this connection. Wait a few minutes before trying again."
    if "403" in message or "forbidden" in message:
        return "The platform refused this download from the current connection. Refresh the video and retry; it may require a signed-in session."
    if "ffmpeg" in message or "ffprobe" in message:
        return "Audio/video conversion failed. Check the FFmpeg installation and try another quality."
    if any(word in message for word in ("private", "login", "log in", "sign in", "cookies", "age-restricted", "confirm you're")):
        return "This video needs a login or is restricted by the platform. Try a publicly accessible video."
    if any(word in message for word in ("unavailable", "not available", "removed", "404")):
        return "This video is unavailable. Check the link or try another video."
    if "format" in message:
        return "That quality is no longer available. Get the video again to refresh its available formats."
    return "The platform could not provide this video. Check your connection and link, then try again."


def inspect_video(url):
    try:
        with yt_dlp.YoutubeDL(options()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("_type") in ("playlist", "multi_video") or info.get("entries") is not None:
            raise MediaError("Please use a link to one video. Playlists and multi-item posts are not supported.")
        if info.get("is_live") or info.get("live_status") == "is_live":
            raise MediaError("This video is live. Try again after the broadcast has finished.")
        return info
    except yt_dlp.utils.DownloadError as error:
        raise MediaError(friendly_error(error)) from error


def video_qualities(info):
    # Include every source resolution; non-MP4 sources are remuxed by FFmpeg.
    return sorted({int(f["height"]) for f in info.get("formats", [])
                   if f.get("height") and f.get("vcodec") not in (None, "none")
                   and not f.get("has_drm")}, reverse=True)


def download_media(url, kind, quality, directory, progress=None):
    opts = options()
    opts["outtmpl"] = str(Path(directory) / "%(title).100B-%(id)s.%(ext)s")

    def hook(data):
        downloaded = data.get("downloaded_bytes", 0)
        if downloaded > MAX_BYTES:
            raise MediaError("This file exceeds the 250 MB download limit. Choose a lower quality.")
        if progress:
            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            progress(min(downloaded / total, 0.99) if total else 0, data.get("status", "downloading"))

    opts["progress_hooks"] = [hook]
    if kind == "MP3":
        opts.update(format="bestaudio/best", postprocessors=[{
            "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(quality),
        }])
    else:
        opts.update(format=f"bestvideo[ext=mp4][height={int(quality)}]+bestaudio[ext=m4a]/best[ext=mp4][height={int(quality)}]/bestvideo[height={int(quality)}]+bestaudio/best[height={int(quality)}]",
                    merge_output_format="mp4", postprocessors=[{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}])
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.extract_info(url, download=True)
        files = list(Path(directory).glob(f"*.{kind.lower()}"))
        if not files:
            raise MediaError("The file could not be prepared, or exceeds 250 MB. Try a lower quality.")
        result = max(files, key=os.path.getmtime)
        if result.stat().st_size > MAX_BYTES:
            raise MediaError("This file exceeds 250 MB. Choose a lower quality.")
        return result
    except yt_dlp.utils.DownloadError as error:
        raise MediaError(friendly_error(error)) from error
