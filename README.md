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

FFmpeg is supplied by imageio-ffmpeg, with an installed system FFmpeg taking precedence. For full YouTube support, install a supported JavaScript runtime such as Deno (https://deno.com/) or Node.js 22+; both are enabled by the app. yt-dlp's default dependencies include its challenge scripts. See https://github.com/yt-dlp/yt-dlp for current platform requirements.

## Flow

The results include a **File name** field. Edit it and press **Apply name** (or Enter) to set the saved filename; extensions and unsafe filename characters are handled automatically. You can rename an already prepared file without downloading or converting it again. After preparation, the exact file size appears in KB or MB above and inside the download button, for both MP4 and MP3.

Choose a platform and MP4/MP3, paste a single video URL, and press **GetVideo**. Choose an available resolution or MP3 conversion bitrate, press **Prepare**, then preview and download the finished file. MP4 choices reflect source resolutions; other containers are remuxed when necessary. Browser playback depends on support for the source codec. MP3 conversion cannot improve the original audio. Animated discovery, download progress, and conversion status communicate each processing stage.

Public videos only; no login or restriction bypass. Platform availability, rate limits, regional restrictions, and extractor changes can prevent a download. Update yt-dlp when a platform changes. Downloads are limited to 250 MB and temporary files are removed after processing. The prepared file is held in the user's Streamlit session; changing inputs clears the result.

This is a local application. Before exposing it publicly, add service-level rate limits, concurrency limits, authentication as appropriate, and restricted outbound networking. URL validation restricts initial links to the selected platform; it is not a complete network sandbox for upstream redirects.

### Connection troubleshooting

`WinError 10013` means outbound access is blocked by the process environment or firewall, not that the video link is invalid. In particular, launching Streamlit inside a restricted agent environment can block all three platforms and both output types. Use `start.bat` from a normal Windows session, or launch it through an approved network-enabled execution. Do not disable your firewall. Platform login requirements and rate limits are separate issues; the app now reports those separately. The `curl-cffi` extra supplies browser-compatible networking when an extractor needs it.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Live verification on 2026-09-25 passed MP4 downloads, MP3 conversion, and decoding of both outputs for the user's YouTube (`IgO9r6OIs8s`), Instagram (`DdrbwZ8ofiw`), and TikTok (`7666839080369392914`) examples. This checks those specific public videos, not every video or every platform restriction. The YouTube link was also verified through the restarted Streamlit UI.

To repeat an explicit live check (downloads temporary files and removes them afterward):

```powershell
.\.venv\Scripts\python.exe tests/live_check.py "YOUR_VIDEO_URL" YouTube
```

Replace `YouTube` with `Instagram` or `TikTok` as appropriate. Run this from a normal network-enabled terminal.
