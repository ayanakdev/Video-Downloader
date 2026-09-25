import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from downloader import download_media, MediaError, friendly_error, download_diagnostics
from yt_dlp.utils import DownloadError


class AudioRetryTests(unittest.TestCase):
    def setUp(self):
        provider = patch("downloader.ensure_provider", return_value="http://127.0.0.1:4416")
        provider.start()
        self.addCleanup(provider.stop)

    def test_missing_format_is_not_missing_video(self):
        message = friendly_error("Requested format is not available. Use --list-formats")
        self.assertIn("usable audio/video format", message)
        self.assertNotIn("This video is unavailable", message)
        self.assertNotIn("This video is unavailable", friendly_error("HTTP Error 404: Not Found"))

    def test_diagnostics_remove_signed_urls_and_tokens(self):
        result = download_diagnostics(["HTTP 403 https://cdn.test/a?signature=secret token=secret"], {})
        self.assertIn("403", result)
        self.assertNotIn("secret", result)

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_last_format_failure_preserves_original_refusal(self, factory):
        factory.return_value.__enter__.return_value.extract_info.side_effect = [
            DownloadError("HTTP Error 403: Forbidden"),
            DownloadError("HTTP Error 403: Forbidden"),
            DownloadError("Requested format is not available"),
        ]
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(MediaError) as caught:
            download_media("https://youtu.be/example", "MP3", 128, directory)
        self.assertIn("refused access", str(caught.exception))
        self.assertIn("Attempt 1", caught.exception.details)
        self.assertIn("Attempt 3", caught.exception.details)
        self.assertEqual(factory.call_args.args[0]["check_formats"], "selected")

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
        self.assertNotIn("extractor_args", attempts[0])
        self.assertEqual(attempts[1]["extractor_args"]["youtube"]["player_client"], ["mweb"])
        self.assertEqual(attempts[1]["postprocessors"][0]["preferredcodec"], "mp3")

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_mp4_refusal_tries_other_clients_at_requested_resolution(self, factory):
        attempts = []
        def client(opts):
            attempts.append(opts)
            instance = MagicMock()
            def extract(*args, **kwargs):
                if len(attempts) < 3:
                    raise DownloadError("HTTP Error 403: Forbidden")
                (Path(opts["outtmpl"]).parent / "finished.mp4").write_bytes(b"video")
            instance.__enter__.return_value.extract_info.side_effect = extract
            return instance
        factory.side_effect = client
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(download_media("https://youtu.be/example", "MP4", 1080, directory).read_bytes(), b"video")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(attempts[2]["extractor_args"]["youtube"]["player_client"], ["web_safari"])
        self.assertTrue(all("height=1080" in opts["format"] for opts in attempts))

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
