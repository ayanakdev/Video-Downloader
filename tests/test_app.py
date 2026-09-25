import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from downloader import MediaError, validate_url, video_qualities, inspect_video, download_media, friendly_error
from download_details import download_filename, format_size


class DownloaderTests(unittest.TestCase):
    def setUp(self):
        provider = patch("downloader.ensure_provider", return_value="http://127.0.0.1:4416")
        provider.start()
        self.addCleanup(provider.stop)

    def test_network_errors_are_actionable_for_every_platform(self):
        for platform in ("YouTube", "Instagram", "TikTok"):
            message = friendly_error(f"ERROR [{platform}] Failed to connect: [WinError 10013] access permissions")
            self.assertIn("start.bat", message)
            self.assertIn("Deployment is not required", message)
        self.assertIn("limiting requests", friendly_error("HTTP Error 429: Too Many Requests"))
        self.assertIn("cannot connect", friendly_error("getaddrinfo failed"))

    def test_platform_validation(self):
        self.assertEqual(validate_url(" https://youtu.be/abc ", "YouTube"), "https://youtu.be/abc")
        for url in ["https://youtube.com.evil.test/watch?v=x", "file:///etc/passwd", "https://localhost/video", "https://instagram.com/reel/x", "https://youtube.com", "https://user:pass@youtube.com/watch?v=x"]:
            with self.subTest(url=url), self.assertRaises(MediaError):
                validate_url(url, "YouTube")

    def test_actual_resolutions_only(self):
        info = {"formats": [
            {"height": 1080, "ext": "mp4", "vcodec": "h264"},
            {"height": 1080, "ext": "mp4", "vcodec": "h264"},
            {"height": 720, "ext": "mp4", "vcodec": "h264"},
            {"height": 2160, "ext": "webm", "vcodec": "vp9"},
            {"height": 480, "ext": "mp4", "vcodec": "h264", "has_drm": True},
        ]}
        self.assertEqual(video_qualities(info), [2160, 1080, 720])

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_playlist_and_live_rejected(self, mock):
        for info in [{"_type": "playlist", "entries": []}, {"is_live": True}]:
            mock.return_value.__enter__.return_value.extract_info.return_value = info
            with self.assertRaises(MediaError):
                inspect_video("https://youtu.be/test")

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_prepared_file_and_conversion_settings(self, mock):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "clip.mp3"
            output.write_bytes(b"audio-test")
            self.assertEqual(download_media("https://youtu.be/test", "MP3", 192, directory), output)
            self.assertEqual(mock.call_args.args[0]["postprocessors"][0]["preferredquality"], "192")


class InterfaceTests(unittest.TestCase):
    def test_rename_preserves_prepared_mp4_and_mp3_and_shows_size(self):
        for kind, quality in [("MP4", 720), ("MP3", 320)]:
            with self.subTest(kind=kind):
                app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
                url = "https://youtu.be/test"
                app.session_state["kind"] = kind
                app.session_state["media"] = {"url": url, "info": {"title": "Long caption", "formats": [{"height": 720, "ext": "mp4", "vcodec": "h264"}]}}
                app.session_state["prepared"] = {"signature": (url, kind, quality), "data": b"x" * 1500, "name": "original"}
                app.run()
                app.text_input(key="filename_input").input("My favorite")
                next(button for button in app.button if button.label == "Apply name").click().run()
                self.assertFalse(app.exception)
                self.assertEqual(app.session_state["download_name"], f"My favorite.{kind.lower()}")
                self.assertEqual(len(app.session_state["prepared"]["data"]), 1500)
                self.assertTrue(any("File size: 1.5 KB" in caption.value for caption in app.caption))

    def test_initial_state_and_validation(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        self.assertFalse(app.exception)
        app.button(key="platform_instagram").click().run()
        self.assertEqual(app.session_state["platform"], "Instagram")
        app.text_input(key="url").input("https://youtube.com/watch?v=test").run()
        app.button(key="get_video").click().run()
        self.assertIn("does not belong", app.error[0].value)
        self.assertFalse(app.exception)

    def test_result_and_reset(self):
        info = {"title": "A sample video", "duration": 65, "formats": [{"height": 720, "ext": "mp4", "vcodec": "h264"}]}
        with patch("downloader.inspect_video", return_value=info):
            app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
            app.text_input(key="url").input("https://youtu.be/test").run()
            app.button(key="get_video").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox[0].value, 720)
            app.radio(key="kind").set_value("MP3").run()
            self.assertIsNone(app.session_state["media"])


class DownloadDetailsTests(unittest.TestCase):
    def test_safe_names_and_extensions(self):
        self.assertEqual(download_filename("My clip.mp4", "MP4"), "My clip.mp4")
        self.assertEqual(download_filename("CON", "MP3"), "GetVideo-CON.mp3")
        self.assertEqual(download_filename(" / : ? ", "MP4"), "GetVideo.mp4")
        self.assertEqual(format_size(1_500_000), "1.50 MB")


if __name__ == "__main__":
    unittest.main()

