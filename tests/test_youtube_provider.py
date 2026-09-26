import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import youtube_provider
from downloader import media_options, MediaError


class ProviderTests(unittest.TestCase):
    @patch("downloader.ensure_provider", return_value="http://127.0.0.1:41234")
    def test_youtube_uses_token_service_for_fresh_extractions(self, provider):
        for url in ("https://youtu.be/3NAWiR0gZ5s", "https://www.youtube.com/watch?v=3NAWiR0gZ5s"):
            args = media_options(url, "mweb")["extractor_args"]
            self.assertEqual(args["youtube"]["player_client"], ["mweb"])
            self.assertEqual(args["youtube"]["fetch_pot"], ["auto"])
            self.assertEqual(args["youtubepot-bgutilhttp"]["base_url"], [provider.return_value])

    @patch("downloader.ensure_provider")
    def test_other_platforms_do_not_start_youtube_service(self, provider):
        for url in ("https://instagram.com/reel/abc", "https://tiktok.com/@user/video/123", "https://youtube.com.evil.test/a"):
            self.assertNotIn("extractor_args", media_options(url))
        provider.assert_not_called()

    @patch("downloader.ensure_provider", side_effect=youtube_provider.ProviderError("npm build failed"))
    def test_setup_failure_does_not_silence_the_client(self, provider):
        # The client is still worth trying untokenised, so this must not raise.
        settings = media_options("https://youtu.be/abc", "mweb")
        self.assertEqual(settings["extractor_args"]["youtube"]["player_client"], ["mweb"])
        self.assertNotIn("youtubepot-bgutilhttp", settings["extractor_args"])

    @patch("downloader.ensure_provider")
    def test_default_youtube_path_does_not_require_token_service(self, provider):
        self.assertNotIn("extractor_args", media_options("https://youtu.be/abc"))
        provider.assert_not_called()

    def test_failed_build_does_not_mark_cache_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "package.json").write_text("{}")
            node = root / "node"
            node.touch()
            npm = root / "lib/node_modules/npm/bin/npm-cli.js"
            npm.parent.mkdir(parents=True)
            npm.touch()
            with patch.object(youtube_provider, "SOURCE", source), patch.object(youtube_provider.tempfile, "gettempdir", return_value=directory), patch.object(youtube_provider.subprocess, "run") as run:
                run.return_value.returncode = 1
                run.return_value.stdout = "failure"
                run.return_value.stderr = ""
                with self.assertRaises(youtube_provider.ProviderError):
                    youtube_provider._build(node)
                self.assertFalse(list(root.rglob(".ready")))


if __name__ == "__main__":
    unittest.main()
