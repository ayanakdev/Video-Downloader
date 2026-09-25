"""Opt-in isolated SABR transport test; does not replace the installed yt-dlp."""
import sys
from pathlib import Path
import tempfile
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / ".sabr-source"))
import yt_dlp
from downloader import media_options


if __name__ == "__main__":
    settings = media_options("https://youtu.be/3NAWiR0gZ5s", "mweb")
    settings["extractor_args"]["youtube"].update(
        player_client=["web"], webpage_client=["web"], formats=["duplicate"])
    kind = sys.argv[1] if len(sys.argv) > 1 else "MP3"
    settings.update(format="bestaudio[protocol=sabr]", no_warnings=False, noprogress=True,
                    postprocessors=[{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "128"}])
    if kind == "MP4":
        settings.update(format="bestvideo[protocol=sabr][ext=mp4][height=1080]+bestaudio[protocol=sabr][ext=m4a]", merge_output_format="mp4",
                        postprocessors=[{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}])
    with tempfile.TemporaryDirectory(prefix="getvideo-sabr-") as directory:
        settings["outtmpl"] = str(Path(directory) / "test.%(ext)s")
        with yt_dlp.YoutubeDL(settings) as ydl:
            info = ydl.extract_info("https://youtu.be/3NAWiR0gZ5s", download=True)
        output = Path(directory) / ("test." + kind.lower())
        subprocess.run([settings["ffmpeg_location"], "-v", "error", "-i", str(output), "-t", "2", "-f", "null", "-"], check=True, capture_output=True)
        print(f"SABR {kind} download and decode OK: {output.stat().st_size} bytes; protocol={info.get('protocol')}")
