"""Real yt-dlp download and FFmpeg conversion against a local generated fixture."""
import functools
import http.server
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

import imageio_ffmpeg
from downloader import download_media


class ConversionTests(unittest.TestCase):
    def test_real_audio_download_and_mp3_conversion(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as output:
            source = Path(root) / "fixture.wav"
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(source)], check=True, capture_output=True)
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=root)
            with http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler) as server:
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    result = download_media(f"http://127.0.0.1:{server.server_port}/fixture.wav", "MP3", 192, output)
                    self.assertEqual(result.suffix, ".mp3")
                    self.assertGreater(result.stat().st_size, 1000)
                    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(result), "-f", "null", "-"], check=True, capture_output=True)
                finally:
                    server.shutdown()
                    thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
