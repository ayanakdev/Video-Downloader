import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from downloader import download_media, MediaError
from yt_dlp.utils import DownloadError


class AudioRetryTests(unittest.TestCase):
    @patch("downloader.yt_dlp.YoutubeDL")
    def test_refused_audio_reextracts_and_uses_isolated_fallback(self, factory):
        attempts = []
        def client(opts):
            attempts.append(opts)
            instance = MagicMock()
            def extract(*args, **kwargs):
                if len(attempts) == 1:
                    raise DownloadError("HTTP Error 403: Forbidden")
                (Path(opts["outtmpl"]).parent / "finished.mp3").write_bytes(b"converted")
            instance.__enter__.return_value.extract_info.side_effect = extract
            return instance
        factory.side_effect = client
        with tempfile.TemporaryDirectory() as directory:
            result = download_media("https://youtu.be/example", "MP3", 192, directory)
            self.assertEqual(result.read_bytes(), b"converted")
            self.assertEqual(result.parent.name, "attempt-2")
        self.assertNotEqual(attempts[0]["format"], attempts[1]["format"])
        self.assertEqual(attempts[1]["postprocessors"][0]["preferredcodec"], "mp3")

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_authentication_failure_is_not_retried(self, factory):
        factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("Sign in to access private video")
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(MediaError):
            download_media("https://youtu.be/example", "MP3", 192, directory)
        self.assertEqual(factory.call_count, 1)

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_retries_are_bounded_for_every_platform(self, factory):
        factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("HTTP Error 403")
        for url in ("https://youtu.be/example", "https://instagram.com/reel/example", "https://www.tiktok.com/@test/video/123"):
            factory.reset_mock()
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(MediaError):
                download_media(url, "MP3", 128, directory)
            self.assertEqual(factory.call_count, 3)
