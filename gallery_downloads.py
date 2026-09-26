"""Download one social post, keeping gallery order and enforcing a total size cap."""
import io
import json
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
sabr_source = ROOT_DIR / ".sabr-source"
if sabr_source.is_dir() and str(sabr_source) not in sys.path:
    sys.path.insert(0, str(sabr_source))

import requests
import yt_dlp
from yt_dlp.extractor.instagram import InstagramIE

from downloader import MAX_BYTES, MediaError, friendly_error, validate_url, options, inspect_video, video_qualities, download_media

MIMES = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/webp": "webp",
    "image/avif": "avif", "image/gif": "gif", "video/mp4": "mp4", "video/quicktime": "mp4",
    "video/webm": "webm"
}


class InstagramGalleryIE(InstagramIE):
    """Reuse yt-dlp's public-post request flow, retaining photos as well as videos."""

    def _extract_product(self, product_info, **kwargs):
        items = []
        for media in product_info.get("carousel_media") or [product_info]:
            versions = media.get("video_versions") or media.get("image_versions2", {}).get("candidates", [])
            versions = [version for version in versions if version.get("url")]
            if not versions:
                raise MediaError("Instagram did not provide every item in this carousel. Please try again later.")
            best = max(versions, key=lambda item: (item.get("width") or 0) * (item.get("height") or 0))
            items.append({"url": best["url"], "headers": {}})
        return {"id": kwargs.get("video_id", "post"), "formats": [{"url": items[0]["url"]}], "gallery_items": items}


def post_url(url, platform):
    url = validate_url(url, platform)
    path = urlparse(url).path
    pattern = r"/(?:p|reel|reels|tv)/[\w-]+/?$" if platform == "Instagram" else r"/@[^/]+/(?:photo|video)/\d+/?$"
    if platform not in ("Instagram", "TikTok") or not re.fullmatch(pattern, path):
        raise MediaError("Paste the full link to one post or carousel, not a profile. For TikTok, use the /photo/ or /video/ link from your browser.")
    return url


def extract_items(url, platform):
    url = post_url(url, platform)
    if platform == "Instagram":
        try:
            with yt_dlp.YoutubeDL(options()) as ydl:
                info = InstagramGalleryIE(ydl).extract(url)
            items = info["gallery_items"]
            if len(items) > 100:
                raise MediaError("This post exceeds the 100-item limit.")
            return items
        except (yt_dlp.utils.ExtractorError, yt_dlp.utils.DownloadError) as error:
            raise MediaError(friendly_error(error).replace("video", "post")) from error
    # Separate processes isolate gallery configuration and cookies between users.
    try:
        result = subprocess.run([
            sys.executable, "-m", "gallery_dl", "--ignore-config", "--dump-json",
            "-o", "videos=merged", "-o", "audio=false", "-o", "previews=false",
            "-o", "timeout=25", "-o", "retries=1", url,
        ], capture_output=True, text=True, encoding="utf-8", timeout=120)
    except subprocess.TimeoutExpired as error:
        raise MediaError("The platform took too long to provide this post. Please try again later.") from error
    if result.returncode:
        raise MediaError(friendly_error(result.stderr).replace("video", "post"))
    try:
        messages = json.loads(result.stdout)
    except ValueError as error:
        raise MediaError("The platform returned an unreadable post. Please try again.") from error
    items = []
    for message in messages:
        if message and message[0] == -1:
            raise MediaError(friendly_error(message[1].get("message", "")).replace("video", "post"))
        if len(message) >= 3 and message[0] == 3:
            media_url, metadata = message[1], message[2]
            if not media_url.startswith("https://"):
                raise MediaError("This post contains a media format that cannot be downloaded yet.")
            items.append({"url": media_url, "headers": metadata.get("_http_headers", {}), "video": metadata.get("type") == "video" or metadata.get("extension") == "mp4"})
    if not items:
        raise MediaError("The platform did not provide this post's media. It may need a login, be unavailable, or be blocked on this connection.")
    if len(items) > 100:
        raise MediaError("This post exceeds the 100-item limit.")
    return items


def download_post(url, platform, progress=None):
    items = extract_items(url, platform)
    if platform == "TikTok" and len(items) == 1 and items[0].get("video"):
        # TikTok gallery video URLs may require a different CDN request flow.
        # The existing video downloader handles those signed URLs and audio muxing.
        info = inspect_video(url)
        qualities = video_qualities(info)
        if not qualities:
            raise MediaError("This TikTok video has no downloadable quality. Try another post.")
        with tempfile.TemporaryDirectory(prefix="getvideo-post-") as directory:
            path = download_media(url, "MP4", max(qualities), directory)
            files = [{"data": path.read_bytes(), "extension": "mp4", "mime": "video/mp4"}]
        if progress:
            progress(1.0, "Prepared 1 of 1 items")
        return files
    files, total = [], 0
    try:
        with requests.Session() as session:
            for index, item in enumerate(items, 1):
                headers = {"User-Agent": "Mozilla/5.0", "Referer": url, **item["headers"]}
                with session.get(item["url"], headers=headers, stream=True, timeout=(15, 30)) as response:
                    response.raise_for_status()
                    mime = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    extension = MIMES.get(mime)
                    if not extension:
                        url_path = urlparse(item["url"]).path.lower()
                        for ext in ("jpg", "jpeg", "png", "webp", "avif", "gif", "mp4", "mov", "webm"):
                            if url_path.endswith(f".{ext}"):
                                extension = "jpg" if ext == "jpeg" else ("mp4" if ext == "mov" else ext)
                                break
                    if not extension:
                        raise MediaError("The platform returned an unsupported file instead of an image or video. Please retry the post.")
                    if total + int(response.headers.get("Content-Length", 0)) > MAX_BYTES:
                        raise MediaError("This post exceeds the total 250 MB download limit.")
                    buffer = io.BytesIO()
                    for chunk in response.iter_content(64 * 1024):
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise MediaError("This post exceeds the total 250 MB download limit.")
                        buffer.write(chunk)
                    if not buffer.tell():
                        raise MediaError("The platform returned an empty media file. Please retry.")
                    files.append({"data": buffer.getvalue(), "extension": extension, "mime": mime})
                if progress:
                    progress(index / len(items), f"Prepared {index} of {len(items)} items")
    except requests.RequestException as error:
        raise MediaError(friendly_error(error).replace("video", "post")) from error
    return files


def gallery_zip(files, name):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for index, item in enumerate(files, 1):
            archive.writestr(f"{name}-{index:02d}.{item['extension']}", item["data"])
    return output.getvalue()
