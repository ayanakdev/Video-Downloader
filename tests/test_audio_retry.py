import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from downloader import (YOUTUBE_CLIENTS, TOKEN_FREE_CLIENTS, TOKEN_CLIENTS, download_media,
                        media_options, MediaError, friendly_error, download_diagnostics, options)
from yt_dlp.utils import DownloadError
from youtube_provider import ProviderError


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

    def test_token_free_clients_are_tried_before_token_gated_ones(self):
        # Datacentre hosts are refused by token-gated clients, so the ladder has
        # to reach a token-free client before it pays for the local token service.
        self.assertEqual(YOUTUBE_CLIENTS[0], "default")
        for client in TOKEN_FREE_CLIENTS:
            self.assertLess(YOUTUBE_CLIENTS.index(client), YOUTUBE_CLIENTS.index(TOKEN_CLIENTS[0]))
        self.assertFalse(set(TOKEN_FREE_CLIENTS) & set(TOKEN_CLIENTS))
        # tv_downgraded aborts the whole run with "page needs to be reloaded".
        self.assertNotIn("tv_downgraded", YOUTUBE_CLIENTS)

    def test_cloud_media_requests_are_forced_to_ipv4(self):
        # googlevideo edges hand out IPv6 media hosts that then refuse the
        # connection, so cloud downloads must not negotiate IPv6.
        self.assertTrue(options()["force_ipv4"])

    def test_proxy_is_applied_only_when_configured(self):
        # A residential proxy is the only real fix for a blocked datacentre IP,
        # and local runs must stay on the direct connection.
        os.environ.pop("GETVIDEO_PROXY", None)
        self.assertNotIn("proxy", options())
        os.environ["GETVIDEO_PROXY"] = "http://user:pass@proxy.test:8080"
        try:
            self.assertEqual(options()["proxy"], "http://user:pass@proxy.test:8080")
        finally:
            os.environ.pop("GETVIDEO_PROXY", None)

    def test_refusal_names_the_missing_proxy_on_hosted_deployments(self):
        bot_wall = "ERROR: [youtube] 7Wi38uVsW98: Sign in to confirm you're not a bot."
        os.environ.pop("GETVIDEO_PROXY", None)
        try:
            # Without a proxy the message must say what is actually missing.
            self.assertIn("GETVIDEO_PROXY", friendly_error("HTTP Error 403: Forbidden"))
            self.assertIn("GETVIDEO_PROXY", friendly_error(bot_wall))
            # With a proxy configured, the hint would be misleading.
            os.environ["GETVIDEO_PROXY"] = "http://proxy.test:8080"
            self.assertNotIn("GETVIDEO_PROXY", friendly_error("HTTP Error 403: Forbidden"))
            self.assertNotIn("GETVIDEO_PROXY", friendly_error(bot_wall))
        finally:
            os.environ.pop("GETVIDEO_PROXY", None)

    def test_bot_wall_is_reported_as_a_host_block_not_a_private_video(self):
        blocked = ("ERROR: [youtube] 7Wi38uVsW98: Sign in to confirm you're not a bot. "
                   "Use --cookies-from-browser or --cookies for the authentication.")
        message = friendly_error(blocked)
        self.assertIn("bot check", message)
        self.assertIn("datacentre", message)
        self.assertNotIn("needs a login", message)
        self.assertIn("reload the page", friendly_error("ERROR: The page needs to be reloaded."))

    def test_withheld_po_token_not_reported_as_a_refused_server(self):
        blocked = ("https formats require a GVS PO Token which was not provided. They will be "
                   "skipped as they may yield HTTP Error 403.")
        self.assertIn("could not verify", friendly_error(blocked))
        self.assertNotIn("datacentre", friendly_error(blocked))
        # "YouTube is forcing SABR streaming" is a format-availability notice,
        # not a claim that the chosen quality is gone.
        notice = "YouTube is forcing SABR streaming for this client."
        self.assertNotIn("no longer available", friendly_error(notice))
        self.assertIn("usable audio/video format", friendly_error(notice))

    def test_refusal_blames_the_hosting_network_not_the_video(self):
        message = friendly_error("HTTP Error 403: Forbidden")
        self.assertIn("datacentre", message)
        self.assertNotIn("private", message)

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_last_format_failure_preserves_original_refusal(self, factory):
        factory.return_value.__enter__.return_value.extract_info.side_effect = [
            DownloadError("HTTP Error 403: Forbidden") for _ in range(len(YOUTUBE_CLIENTS) - 1)
        ] + [DownloadError("Requested format is not available")]
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(MediaError) as caught:
            download_media("https://youtu.be/example", "MP3", 128, directory)
        self.assertIn("refused", str(caught.exception))
        self.assertIn("Attempt 1", caught.exception.details)
        self.assertIn(f"Attempt {len(YOUTUBE_CLIENTS)}", caught.exception.details)
        self.assertEqual(factory.call_args.args[0]["format"], "bestaudio[protocol=sabr]")

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
        self.assertEqual(attempts[1]["extractor_args"]["youtube"]["player_client"], [TOKEN_FREE_CLIENTS[1]])
        self.assertEqual(attempts[1]["postprocessors"][0]["preferredcodec"], "mp3")

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_mp4_sorts_to_resolution_instead_of_forcing_an_itag(self, factory):
        # A forced itag skips the token check and 403s even on public videos.
        attempts = []
        def client(opts):
            attempts.append(opts)
            instance = MagicMock()
            def extract(*args, **kwargs):
                (Path(opts["outtmpl"]).parent / "finished.mp4").write_bytes(b"video")
            instance.__enter__.return_value.extract_info.side_effect = extract
            return instance
        factory.side_effect = client
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(download_media("https://youtu.be/example", "MP4", 1080, directory).read_bytes(), b"video")
        self.assertEqual(attempts[0]["format"], "bestvideo+bestaudio/best")
        self.assertIn("res:1080", attempts[0]["format_sort"])
        self.assertFalse(any("height=" in opts["format"] for opts in attempts))

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_refused_mp4_walks_every_client_and_ends_on_sabr(self, factory):
        attempts = []
        def client(opts):
            attempts.append(opts)
            instance = MagicMock()
            def extract(*args, **kwargs):
                if len(attempts) < len(YOUTUBE_CLIENTS):
                    raise DownloadError("HTTP Error 403: Forbidden")
                (Path(opts["outtmpl"]).parent / "finished.mp4").write_bytes(b"video")
            instance.__enter__.return_value.extract_info.side_effect = extract
            return instance
        factory.side_effect = client
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(download_media("https://youtu.be/example", "MP4", 1080, directory).read_bytes(), b"video")
        self.assertEqual(len(attempts), len(YOUTUBE_CLIENTS))
        self.assertEqual(attempts[-1]["extractor_args"]["youtube"]["player_client"], [TOKEN_CLIENTS[-1]])
        self.assertIn("protocol=sabr", attempts[-1]["format"])

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_authentication_failure_is_not_retried(self, factory):
        factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("Sign in to access private video")
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(MediaError):
            download_media("https://youtu.be/example", "MP3", 192, directory)
        self.assertEqual(factory.call_count, 1)

    @patch("downloader.ensure_provider", side_effect=ProviderError("setup failed"))
    @patch("downloader.yt_dlp.YoutubeDL")
    def test_provider_setup_failure_still_reaches_token_free_clients(self, factory, provider):
        factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("HTTP Error 403")
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(MediaError) as caught:
            download_media("https://youtu.be/example", "MP4", 1080, directory)
        # A dead token service must not consume the whole ladder.
        self.assertEqual(factory.call_count, len(YOUTUBE_CLIENTS))
        self.assertIn("refused", str(caught.exception))
        self.assertIn("setup failed", caught.exception.details)

    @patch("downloader.ensure_provider", side_effect=ProviderError("service down"))
    def test_token_client_still_attempted_without_a_token(self, provider):
        # Some itags are served untokenised, so a dead token service must not
        # remove the client from the ladder entirely.
        settings = media_options("https://youtu.be/example", TOKEN_CLIENTS[0])
        self.assertEqual(settings["extractor_args"]["youtube"]["player_client"], [TOKEN_CLIENTS[0]])
        self.assertNotIn("fetch_pot", settings["extractor_args"]["youtube"])
        self.assertNotIn("youtubepot-bgutilhttp", settings["extractor_args"])

    @patch("downloader.yt_dlp.YoutubeDL")
    def test_retries_are_bounded_for_every_platform(self, factory):
        factory.return_value.__enter__.return_value.extract_info.side_effect = DownloadError("HTTP Error 403")
        for url in ("https://youtu.be/example", "https://instagram.com/reel/example", "https://www.tiktok.com/@test/video/123"):
            factory.reset_mock()
            with tempfile.TemporaryDirectory() as directory, self.assertRaises(MediaError):
                download_media(url, "MP3", 128, directory)
            expected = len(YOUTUBE_CLIENTS) if "youtu.be" in url else 3
            self.assertEqual(factory.call_count, expected)
