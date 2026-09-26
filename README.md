# GetVideo

A white-and-red Streamlit video and audio downloader for public YouTube, Instagram, and TikTok videos. Uses the supplied logo in `assets/` and yt-dlp for extraction.

## Run locally

On this configured Windows project, double-click `start.bat`. It runs GetVideo in your normal Windows session with access to the internet. No website deployment is needed. If port 8501 is already in use, stop the previous GetVideo process before starting another.

Python 3.10 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

On macOS/Linux, replace `.venv\Scripts\python.exe` with `.venv/bin/python`.

FFmpeg is supplied by imageio-ffmpeg, with an installed system FFmpeg taking precedence. Node.js 24 is supplied by `nodejs-wheel`, and yt-dlp's default dependencies include its challenge scripts. YouTube also uses the bundled PO-token service described below. See https://github.com/yt-dlp/yt-dlp for current platform requirements.

## Flow

Instagram and TikTok now have **Reel**, **Post**, and **Carousel** selectors. Reel retains MP4/MP3 options. Post and Carousel fetch the original images and videos from one post, with individual downloads and an ordered ZIP for multiple items. Both modes keep every item, including mixed image/video carousels; a single-image post needs no ZIP. Downloads show exact sizes and support custom names. The total post limit is 250 MB / 100 items. TikTok photo posts require a full `/@user/photo/id` link (open short links in your browser first).

Photo/gallery extraction uses gallery-dl for TikTok and the public-post request flow in yt-dlp for Instagram. Some posts require authentication or are blocked by the platform, especially on cloud hosting; those return an error rather than a partial gallery. No browser cookies are loaded automatically. The Instagram gallery adapter uses a yt-dlp internal extraction hook, so verify it when updating yt-dlp.

Deploy the updated `requirements.txt`, `gallery_downloads.py`, `gallery_ui.py`, `app.py`, and `download_details.py` together. The local server is still stopped. On 2026-09-25, the supplied Instagram carousel `DdgzPw7knxy` was verified to return all six JPG files. TikTok photo extraction has fixture coverage; a live photo-post example is still needed for verification.

The results include a **File name** field. Edit it and press **Apply name** (or Enter) to set the saved filename; extensions and unsafe filename characters are handled automatically. You can rename an already prepared file without downloading or converting it again. After preparation, the exact file size appears in KB or MB above and inside the download button, for both MP4 and MP3.

Choose a platform and MP4/MP3, paste a single video URL, and press **GetVideo**. Choose an available resolution or MP3 conversion bitrate, press **Prepare**, then preview and download the finished file. MP4 choices reflect source resolutions; other containers are remuxed when necessary. Browser playback depends on support for the source codec. MP3 conversion cannot improve the original audio. Animated discovery, download progress, and conversion status communicate each processing stage.

Public videos only; no login or restriction bypass. Platform availability, rate limits, regional restrictions, and extractor changes can prevent a download. Update yt-dlp when a platform changes. Downloads are limited to 250 MB and temporary files are removed after processing. The prepared file is held in the user's Streamlit session; changing inputs clears the result. If the app owner configures `GETVIDEO_COOKIES`, requests are made as that signed-in account, which is their decision to make and which the README documents.

This is a local application. Before exposing it publicly, add service-level rate limits, concurrency limits, authentication as appropriate, and restricted outbound networking. URL validation restricts initial links to the selected platform; it is not a complete network sandbox for upstream redirects.

### Connection troubleshooting

Production uses `server.fileWatcherType = "none"` to avoid Streamlit's module-reloading race during a GitHub update (`KeyError: 'download_details'` inside Python's import machinery). After deploying code changes, use **Manage app → Reboot app** to start a clean process. This deliberately disables local file hot reload too; restart the local server after editing, or override with `--server.fileWatcherType auto` for development. `download_details.py` must remain in the repository root; it is already tracked.

**Reboot does not always pick up new commits.** A reboot restarts the container from the image built by the last deploy; it does not re-clone the repository. Streamlit Cloud's log panel shows the deploy log, and **its timestamps are UTC while your machine may be several hours ahead** — comparing the two wrongly suggests the app is stale. Confirm a deploy is current by expanding **Download error details** in the app and checking the revision line matches the code you pushed. If it does not, the deploy has not completed.

If all YouTube formats fail from Community Cloud while the same URL downloads locally, changing MP3 bitrates is not a reliable fix. Media requests are being refused before FFmpeg conversion. Node/EJS solves JavaScript challenges; it does not supply playback tokens. GetVideo can fall back to yt-dlp's recommended `mweb` client with automatic GVS Proof of Origin tokens through `bgutil-ytdlp-pot-provider` for both MP3 and MP4 (https://github.com/yt-dlp/yt-dlp/wiki/PO-Token-Guide).

### Hosted deployments: cookies or a proxy

**This is the fix for HTTP 403 / "Sign in to confirm you're not a bot" on Streamlit Community Cloud.** Those are IP-based refusals at the media CDN: platforms block datacentre IP ranges, so the same public link downloads on a home connection and fails on the cloud host. No client, token, or format change can repair a refusal that happens before any media bytes arrive, and metadata can still succeed while every media request is blocked.

Two optional secrets, both set in **Manage app → Secrets**. Neither is needed locally, since home IPs are not blocked.

**1. Cookies (free).** The bot wall asks for a signed-in session, so a cookie export is the free route. Export Netscape-format `cookies.txt` from a signed-in browser session using a cookies.txt extension, then add it as a single secret:

```
GETVIDEO_COOKIES
```

Paste the whole file contents as the value. The app writes it once per process to a private temp file and passes it to yt-dlp as `cookiefile`. Use an account you are willing to expose, because a public app's requests are made as that signed-in user. Cookies expire every few weeks, so expect to re-export when downloads start failing again.

**2. Proxy (paid, more reliable).** For a residential proxy:

```
GETVIDEO_PROXY = "http://user:pass@host:port"
```

Passed to yt-dlp as its `proxy` option; `http://`, `https://`, and `socks5://` are accepted. `GETVIDEO_PROXY` is also read from the environment. Cheap datacentre proxies score the same as the host IP and rarely help; use a residential or ISP exit.

When neither is configured, the 403 and bot-wall errors say so explicitly, and **Download error details** reports `Outbound proxy configured` and `Cookies configured`. Cookie values and the temp file path never appear in diagnostics.

### Client ladder

YouTube requests walk a ladder of clients, best first, stopping at the first success: `default`, `visionos`, `web_embedded`, `android_vr` (these need no Proof-of-Origin token), then `mweb` and `web` with the bundled token service. MP4 sorts to the requested resolution with `format_sort` instead of forcing one itag, because a forced itag skips the token check and returns 403 on public videos. Cloud downloads force IPv4, since googlevideo hands out IPv6 media hosts that then refuse the connection. A token service that fails to start no longer removes its rung: the client is still tried untokenised and the reason is recorded in the error details.

### Deploying the YouTube token service

**SABR update (2026-09-25), superseding the older client correction below:** after a full reboot, production rejected the default client's media with HTTP 403 and returned SABR-only/missing-URL responses for `mweb`. The final fallback now uses the `web` client and explicitly selects `protocol=sabr`, with tokens. `requirements.txt` pins maintainer coletdjnz's upstream PR #13515 implementation at commit `6ef0ae00f0a4e9dd042193b3f5a2bb28b5fc0ca6`. This is experimental, unmerged upstream code, not the stable PyPI release. Keep the exact commit pinned until another version is tested. Deploy `requirements.txt` along with `downloader.py` and rebuild/reboot; copying Python code alone cannot add SABR support. The diagnostics revision is now `2026-09-26-client-ladder`. This adds transport support and cannot guarantee access from every server/network.

Production checks after the client-fallback reboot: Instagram MP4 (2.71 MB), Instagram MP3 (538.3 KB), TikTok MP4 (1.17 MB), TikTok MP3 (291.5 KB), and the Instagram carousel (six JPGs; 2.15 MB ZIP) all reached the ready/download state for the supplied examples. YouTube MP4 and MP3 failed on that deployment. TikTok photo-post production verification still needs a photo link. These sample checks do not cover every URL, quality, or restriction.

**Latest client correction:** metadata and downloads start with yt-dlp's default clients again. YouTube MP4 and MP3 media refusals now trigger fresh extraction with `mweb` plus tokens, then `web_safari`, with at most three attempts and separate output directories. A token-service setup failure is recorded and does not prevent trying the remaining client. The selected MP4 resolution is preserved. Authentication and rate-limit failures are not repeatedly retried. This corrects the earlier change that forced every YouTube request through `mweb` and left MP4 without a fallback. It does not establish that Community Cloud accepts any of these requests; verify on that host after deployment.

Upload the complete updated repository, including **`youtube_provider.py`, `vendor/bgutil/` (all files), `packages.txt`, `requirements.txt`, and `downloader.py`**. A Python-only upload is insufficient. Then use **Manage app → Reboot app** so Community Cloud installs the new Python and system dependencies and starts a clean process. No cookies, API key, separate Node server, or public port are required.

The first YouTube request requiring the `mweb` fallback installs the locked npm dependencies and builds the bundled upstream v2.0.0 server in a temporary runtime cache. This can take several minutes on a fresh host. Subsequent fallback requests reuse the build and service. Builds use a cross-process file lock, starts use a thread lock, and the service binds only to loopback on a dynamically chosen port. Node is located from the Python wheel; npm does not need to be on PATH. `packages.txt` supplies Linux libraries if canvas needs a native build. The service stops with the app process and is restarted if it exits. Instagram/TikTok do not start or use this service.

Build failures appear in Streamlit's server logs; service logs are in the temporary `getvideo-pot-*/service-*.log` directory. Setup errors are reported separately from missing videos. The bundled server's source, lockfile, attribution, and GPL-3.0 license are included in `vendor/bgutil/`.

Playback tokens address a missing part of the request flow, but do not guarantee access from a blocked cloud IP. If token-bearing media requests still get HTTP 403 on the deployed server, that host/network needs investigation; changing conversion libraries cannot repair a refusal before media bytes arrive. Local success does not verify Community Cloud.

MP3 downloads now check source stream availability before selection. Error classification distinguishes missing formats from unavailable videos, and a failed last-resort format no longer masks an earlier HTTP 403. On failure, expand **Download error details** in the app to see installed dependency versions, whether Node was found, extractor warnings, and the errors from each attempt. Signed URLs are omitted. Share this diagnostic text or the Python logs from **Manage app → Logs**; browser-console iframe warnings and `/api/v2/user/details` requests do not show the server-side yt-dlp failure.

The deployment dependencies now include Node.js 24 via `nodejs-wheel`, and the downloader explicitly locates the bundled executable. This supplies YouTube's JavaScript runtime even when the host has no suitable Node.js on PATH. MP3 preparation retries a refused/expired media URL with freshly extracted alternate audio formats and then an audio-bearing video format, up to three attempts. Authentication errors and rate limits are not repeatedly retried. Missing media fragments fail rather than producing incomplete files.

Follow the complete token-service deployment checklist above, rather than uploading only `downloader.py`. The screenshot's YouTube example `3NAWiR0gZ5s` worked locally before these changes too, so a production verification remains necessary.

`WinError 10013` means outbound access is blocked by the process environment or firewall, not that the video link is invalid. In particular, launching Streamlit inside a restricted agent environment can block all three platforms and both output types. Use `start.bat` from a normal Windows session, or launch it through an approved network-enabled execution. Do not disable your firewall. Platform login requirements and rate limits are separate issues; the app now reports those separately. The `curl-cffi` extra supplies browser-compatible networking when an extractor needs it.

## Tests

Token-provider verification on 2026-09-25: `3NAWiR0gZ5s` exposed 35 token-bearing media formats through `mweb`; MP3 downloaded and decoded (3,277,868 bytes). The token-enabled client also passed MP4 download/decoding (5,553,667 bytes). The supplied Instagram and TikTok links passed MP3 download/decoding again. All 26 automated tests passed. These runs were local, not on Streamlit Community Cloud.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Live verification on 2026-09-25 passed MP4 downloads, MP3 conversion, and decoding of both outputs for the user's YouTube (`IgO9r6OIs8s`), Instagram (`DdrbwZ8ofiw`), and TikTok (`7666839080369392914`) examples. This checks those specific public videos, not every video or every platform restriction. The YouTube link was also verified through the restarted Streamlit UI.

To repeat an explicit live check (downloads temporary files and removes them afterward):

```powershell
.\.venv\Scripts\python.exe tests/live_check.py "YOUR_VIDEO_URL" YouTube
```

Replace `YouTube` with `Instagram` or `TikTok` as appropriate. Run this from a normal network-enabled terminal.
