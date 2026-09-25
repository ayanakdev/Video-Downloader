"""Opt-in live smoke test: python tests/live_check.py URL PLATFORM [MP4 MP3]."""
import sys
from pathlib import Path
import tempfile
import subprocess
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import imageio_ffmpeg
from downloader import inspect_video, download_media, validate_url, video_qualities


if __name__ == "__main__":
    url, platform, *kinds = sys.argv[1:]
    url = validate_url(url, platform)
    info = inspect_video(url)
    qualities = video_qualities(info)
    print(f"{platform}: metadata OK; resolutions={qualities}", flush=True)
    if platform == "YouTube":
        token_formats = sum(bool(parse_qs(urlparse(f.get("url", "")).query).get("pot"))
                            or "/pot/" in f.get("url", "") for f in info.get("formats", []))
        if not token_formats:
            raise RuntimeError("No token-bearing media formats found; provider integration is unverified")
        print(f"YouTube: {token_formats} media formats include a playback token", flush=True)
    for kind in kinds or ["MP4", "MP3"]:
        quality = min(qualities) if kind == "MP4" else 128
        with tempfile.TemporaryDirectory(prefix="getvideo-live-") as directory:
            path = download_media(url, kind, quality, directory)
            # Decode a sample of the real downloaded file, not just its extension.
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path), "-t", "2", "-f", "null", "-"], check=True, capture_output=True)
            print(f"{platform}: {kind} download and decode OK ({path.stat().st_size} bytes)", flush=True)
