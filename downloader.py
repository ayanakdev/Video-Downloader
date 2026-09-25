"""Single-video extraction and conversion, isolated from the Streamlit interface."""
from pathlib import Path
from urllib.parse import urlparse
import os
import shutil
import importlib.util
import re
from importlib.metadata import version, PackageNotFoundError

import imageio_ffmpeg
import yt_dlp
from youtube_provider import ensure_provider, ProviderError

PLATFORMS = {"YouTube": ("youtube.com", "youtu.be"), "Instagram": ("instagram.com",), "TikTok": ("tiktok.com",)}
MAX_BYTES = 250 * 1024 * 1024


class MediaError(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details


def download_diagnostics(errors, settings):
    """Keep useful provider failures without exposing signed URLs or local paths."""
    packages = ["Downloader revision: 2026-09-25-sabr-fallback"]
    for name in ("yt-dlp", "yt-dlp-ejs", "nodejs-wheel", "bgutil-ytdlp-pot-provider"):
        try:
            packages.append(f"{name}: {version(name)}")
        except PackageNotFoundError:
            packages.append(f"{name}: not installed")
    node = settings.get("js_runtimes", {}).get("node", {}).get("path")
    packages.append(f"Node executable found: {bool(node and Path(node).is_file())}")
    youtube = settings.get("extractor_args", {}).get("youtube", {})
    packages.append(f"YouTube client: {','.join(youtube.get('player_client', ['default']))}")
    packages.append(f"Local token provider configured: {bool(settings.get('extractor_args', {}).get('youtubepot-bgutilhttp'))}")
    for entry in errors:
        entry = re.sub(r"\x1b\[[0-9;]*m", "", str(entry))
        entry = re.sub(r"https?://\S+", "[URL omitted]", entry)
        entry = re.sub(r"(?i)(cookie|authorization|token)\s*[:=]\s*\S+", r"\1=[omitted]", entry)
        packages.append(entry[:1800])
    return "\n".join(packages)


class DownloadLogger:
    def __init__(self):
        self.messages = []

    def debug(self, message):
        pass

    def warning(self, message):
        self.messages.append(str(message))
        self.messages = self.messages[-12:]

    def error(self, message):
        self.warning(message)


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
    node_path = shutil.which("node")
    spec = importlib.util.find_spec("nodejs_wheel")
    if spec and spec.origin:
        root = Path(spec.origin).parent
        for candidate in (root / "bin" / "node", root / "node.exe", root / "bin" / "node.exe"):
            if candidate.is_file():
                node_path = str(candidate)
                break
    return {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "socket_timeout": 25, "retries": 2, "extractor_retries": 2,
        "max_filesize": MAX_BYTES, "cachedir": False,
        "ffmpeg_location": shutil.which("ffmpeg") or imageio_ffmpeg.get_ffmpeg_exe(),
        "restrictfilenames": True,
        "js_runtimes": {"deno": {}, "node": {"path": node_path} if node_path else {}},
        "skip_unavailable_fragments": False,
    }


def is_youtube(url):
    host = (urlparse(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in PLATFORMS["YouTube"])


def media_options(url, client="default"):
    settings = options()
    if is_youtube(url) and client != "default":
        settings["extractor_args"] = {"youtube": {"player_client": [client], "fetch_pot": ["auto"]}}
    if is_youtube(url) and client in ("mweb", "web"):
        try:
            version("bgutil-ytdlp-pot-provider")
            endpoint = ensure_provider(settings["js_runtimes"]["node"].get("path"))
        except (ProviderError, PackageNotFoundError, OSError) as error:
            raise MediaError("YouTube's download service could not start. Please check the app's setup.", str(error)) from error
        settings["extractor_args"] = {
            "youtube": {"player_client": [client], "fetch_pot": ["auto"]},
            "youtubepot-bgutilhttp": {"base_url": [endpoint]},
        }
        if client == "web":
            settings["extractor_args"]["youtube"].update(webpage_client=["web"], formats=["duplicate"])
    return settings


def retryable_error(error):
    return any(token in str(error).lower() for token in (
        "403", "forbidden", "410", "requested format is not available", "no suitable formats", "no video formats"))


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
        return ("The platform refused access from this server. Alternative audio sources may also be blocked. "
                "If the same link works locally, the hosting server's connection may be restricted; "
                "retry later or contact the app owner. This does not necessarily mean the video is private.")
    if "ffmpeg" in message or "ffprobe" in message:
        return "Audio/video conversion failed. Check the FFmpeg installation and try another quality."
    if any(word in message for word in ("private", "login", "log in", "sign in", "cookies", "age-restricted", "confirm you're")):
        return "This video needs a login or is restricted by the platform. Try a publicly accessible video."
    if any(word in message for word in ("requested format", "no suitable formats", "no video formats", "only images are available")):
        return "The platform did not provide a usable audio/video format to this server. The video itself may still be available."
    if "404" in message or "410" in message:
        return "A media request failed or its download link expired. This does not establish that the video was removed. Try fetching the video again."
    if any(word in message for word in ("video unavailable", "video is unavailable", "video has been removed", "video not available")):
        return "This video is unavailable. Check the link or try another video."
    if "format" in message:
        return "That quality is no longer available. Get the video again to refresh its available formats."
    return "The platform could not provide this video. Check your connection and link, then try again."


def inspect_video(url):
    settings = media_options(url)
    logger = DownloadLogger()
    settings.update(logger=logger, no_warnings=False)
    try:
        clients = ("default", "mweb", "web") if is_youtube(url) else ("default",)
        for index, client in enumerate(clients):
            settings = media_options(url, client)
            settings.update(logger=logger, no_warnings=False)
            try:
                with yt_dlp.YoutubeDL(settings) as ydl:
                    info = ydl.extract_info(url, download=False)
                break
            except yt_dlp.utils.DownloadError as error:
                if index == len(clients) - 1 or not retryable_error(error):
                    raise
        if not info or info.get("_type") in ("playlist", "multi_video") or info.get("entries") is not None:
            raise MediaError("Please use a link to one video. Playlists and multi-item posts are not supported.")
        if info.get("is_live") or info.get("live_status") == "is_live":
            raise MediaError("This video is live. Try again after the broadcast has finished.")
        return info
    except yt_dlp.utils.DownloadError as error:
        raise MediaError(friendly_error(error), download_diagnostics([*logger.messages, str(error)], settings)) from error


def video_qualities(info):
    # Include every source resolution; non-MP4 sources are remuxed by FFmpeg.
    return sorted({int(f["height"]) for f in info.get("formats", [])
                   if f.get("height") and f.get("vcodec") not in (None, "none")
                   and not f.get("has_drm")}, reverse=True)


def download_media(url, kind, quality, directory, progress=None):
    opts = media_options(url)
    logger = DownloadLogger()
    opts.update(logger=logger, no_warnings=False)
    failures = []
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
        opts.update(format="bestaudio/best", check_formats="selected", postprocessors=[{
            "key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": str(quality),
        }])
    else:
        opts.update(format=f"bestvideo[ext=mp4][height={int(quality)}]+bestaudio[ext=m4a]/best[ext=mp4][height={int(quality)}]/bestvideo[height={int(quality)}]+bestaudio/best[height={int(quality)}]",
                    merge_output_format="mp4", postprocessors=[{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}])
    try:
        selectors = [opts["format"]]
        youtube = is_youtube(url)
        if youtube:
            # Change the request client, not just the format on the same refused client.
            selectors *= 3
        elif kind == "MP3":
            # A slash fallback only handles absent formats, not HTTP failures.
            # Re-extract fresh URLs and try other audio sources on a refusal.
            selectors += ["bestaudio[ext=m4a]/bestaudio[ext=webm]", "best[vcodec!=none][acodec!=none]"]
        for attempt, selector in enumerate(selectors):
            target = Path(directory) if attempt == 0 else Path(directory) / f"attempt-{attempt + 1}"
            target.mkdir(parents=True, exist_ok=True)
            attempt_opts = {**opts, "format": selector, "outtmpl": str(target / "%(title).100B-%(id)s.%(ext)s")}
            client = ("default", "mweb", "web")[attempt] if youtube else "platform default"
            if youtube and attempt:
                try:
                    attempt_opts.update(media_options(url, client))
                    attempt_opts.update(logger=logger, no_warnings=False)
                except MediaError as error:
                    failures.append(f"Attempt {attempt + 1} ({client}): {error}; {error.details}")
                    if progress:
                        progress(0.0, "retrying")
                    continue
            if youtube and client == "web":
                # SABR supplies media through a different transport, not signed HTTPS URLs.
                attempt_opts["format"] = ("bestaudio[protocol=sabr]" if kind == "MP3" else
                    f"bestvideo[protocol=sabr][ext=mp4][height={int(quality)}]+bestaudio[protocol=sabr][ext=m4a]/bestvideo[protocol=sabr][height={int(quality)}]+bestaudio[protocol=sabr]")
                attempt_opts.pop("check_formats", None)
                selector = attempt_opts["format"]
            try:
                with yt_dlp.YoutubeDL(attempt_opts) as ydl:
                    ydl.extract_info(url, download=True)
                break
            except yt_dlp.utils.DownloadError as error:
                failures.append(f"Attempt {attempt + 1} ({client}; {selector}): {error}")
                if not retryable_error(error) or attempt == len(selectors) - 1:
                    raise
                if progress:
                    progress(0.0, "retrying")
        else:
            raise yt_dlp.utils.DownloadError("All download sources failed. " + "\n".join(failures))
        files = list(target.glob(f"*.{kind.lower()}"))
        if not files:
            raise MediaError("The file could not be prepared, or exceeds 250 MB. Try a lower quality.")
        result = max(files, key=os.path.getmtime)
        if result.stat().st_size > MAX_BYTES:
            raise MediaError("This file exceeds 250 MB. Choose a lower quality.")
        return result
    except yt_dlp.utils.DownloadError as error:
        # An absent last-resort format must not conceal the original 403.
        cause = next((failure for failure in [*failures, *logger.messages] if "403" in failure or "forbidden" in failure.lower()), str(error))
        raise MediaError(friendly_error(cause), download_diagnostics([*logger.messages, *failures], opts)) from error
