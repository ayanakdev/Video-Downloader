import io
import json
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from streamlit.testing.v1 import AppTest
from pathlib import Path
from gallery_downloads import InstagramGalleryIE, extract_items, post_url, gallery_zip, download_post
from downloader import MediaError


class GalleryTests(unittest.TestCase):
    def test_single_post_urls_only(self):
        for platform, url in [("Instagram", "https://instagram.com/someone/"), ("TikTok", "https://www.tiktok.com/@someone")]:
            with self.assertRaises(MediaError):
                post_url(url, platform)
        self.assertIn("/photo/", post_url("https://www.tiktok.com/@someone/photo/123", "TikTok"))

    def test_instagram_mixed_carousel_order_and_best_size(self):
        info = {"carousel_media": [
            {"image_versions2": {"candidates": [{"url": "https://cdn.test/small", "width": 10, "height": 10}, {"url": "https://cdn.test/photo", "width": 100, "height": 100}]}},
            {"video_versions": [{"url": "https://cdn.test/video", "width": 100, "height": 100}]},
        ]}
        result = InstagramGalleryIE()._extract_product(info, video_id="test")
        self.assertEqual([item["url"] for item in result["gallery_items"]], ["https://cdn.test/photo", "https://cdn.test/video"])

    @patch("gallery_downloads.subprocess.run")
    def test_tiktok_photo_messages_and_errors(self, run):
        run.return_value = SimpleNamespace(returncode=0, stdout=json.dumps([[3, "https://cdn.test/one.jpg", {}], [3, "https://cdn.test/two.jpg", {}]]))
        self.assertEqual(len(extract_items("https://www.tiktok.com/@someone/photo/123", "TikTok")), 2)
        run.return_value.stdout = json.dumps([[-1, {"message": "login required"}]])
        with self.assertRaisesRegex(MediaError, "login"):
            extract_items("https://www.tiktok.com/@someone/photo/123", "TikTok")

    def test_zip_preserves_all_original_files(self):
        files = [{"extension": "jpg", "data": b"photo"}, {"extension": "mp4", "data": b"video"}]
        with zipfile.ZipFile(io.BytesIO(gallery_zip(files, "My post"))) as archive:
            self.assertEqual(archive.namelist(), ["My post-01.jpg", "My post-02.mp4"])
            self.assertEqual(archive.read("My post-02.mp4"), b"video")

    @patch("gallery_downloads.extract_items", return_value=[{"url": "https://cdn.test/a", "headers": {}}] * 2)
    @patch("gallery_downloads.requests.Session")
    @patch("gallery_downloads.MAX_BYTES", 5)
    def test_cumulative_size_limit(self, session, extract):
        response = MagicMock()
        response.headers = {"Content-Type": "image/jpeg"}
        response.iter_content.side_effect = lambda *args: iter([b"123"])
        session.return_value.__enter__.return_value.get.return_value.__enter__.return_value = response
        with self.assertRaisesRegex(MediaError, "250 MB"):
            download_post("https://instagram.com/p/test", "Instagram")

    def test_content_selector_and_reset(self):
        app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / "app.py")).run()
        app.button(key="platform_instagram").click().run()
        self.assertEqual(app.radio(key="content_type").options, ["Reel", "Post", "Carousel"])
        app.radio(key="content_type").set_value("Carousel").run()
        self.assertFalse(any(radio.key == "kind" for radio in app.radio))
        app.session_state["gallery_files"] = [{"extension": "mp4", "mime": "video/mp4", "data": b"test"}]
        app.run()
        self.assertFalse(app.exception)
        app.button(key="platform_youtube").click().run()
        self.assertNotIn("gallery_files", app.session_state)
        self.assertFalse(app.exception)


if __name__ == "__main__":
    unittest.main()
