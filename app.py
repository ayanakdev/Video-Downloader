from pathlib import Path
import base64
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sabr_source = ROOT / ".sabr-source"
if sabr_source.is_dir() and str(sabr_source) not in sys.path:
    sys.path.insert(0, str(sabr_source))

import streamlit as st

from downloader import MediaError, PLATFORMS, download_media, inspect_video, validate_url, video_qualities
from download_details import download_filename, format_size
from gallery_downloads import download_post
from gallery_ui import render_gallery

# Cloud and datacentre IP ranges are blocked by video platforms. Setting
# GETVIDEO_PROXY in Streamlit secrets (or the environment) to a residential
# proxy is what makes hosted downloads work; home IPs need no proxy.
try:
    _proxy = st.secrets.get("GETVIDEO_PROXY")
except Exception:
    _proxy = None
_proxy = (_proxy or "").strip() if isinstance(_proxy, str) else ""
if _proxy:
    import os
    os.environ["GETVIDEO_PROXY"] = _proxy

ROOT = Path(__file__).parent
st.set_page_config(page_title="GetVideo — Keep the good stuff.", page_icon=str(ROOT / "assets/videogetLOGO.png"), layout="centered")
st.html(f"<style>{(ROOT / 'style.css').read_text(encoding='utf-8')}</style>")
logo = base64.b64encode((ROOT / "assets/videogetLOGO.png").read_bytes()).decode()
st.html(f'''<nav class="nav"><a class="brand" href="/" aria-label="GetVideo home"><img src="data:image/png;base64,{logo}" alt="GetVideo logo"><span>Get<span class="red">Video</span></span></a><span class="nav-note">A little link. A lot to keep.</span><span class="nav-pill">VIDEO & AUDIO <span>↗</span></span></nav>
<section class="hero"><div class="eyebrow"><span></span> YOUR FAVORITES, WITH YOU.</div><h1>Keep the <span>good stuff.</span></h1><p>That video worth saving. That sound on repeat.<br>One link is all you need.</p></section>''')

for key, default in {"platform": "YouTube", "kind": "MP4", "media": None, "prepared": None, "error": None}.items():
    st.session_state.setdefault(key, default)


def clear_result():
    st.session_state.media = None
    st.session_state.prepared = None
    st.session_state.error = None
    st.session_state.pop("error_details", None)
    st.session_state.pop("download_name", None)
    st.session_state.pop("filename_input", None)
    for key in ("gallery_files", "gallery_name", "gallery_zip"):
        st.session_state.pop(key, None)


with st.container(key="download_card", border=True):
    st.html('<div class="card-heading"><div><span class="tiny-label">THE DOWNLOADER</span><h2>Your next offline favorite.</h2></div><span class="corner-arrow">↙</span></div><div class="field-label"><b>01</b> Pick your platform</div>')
    columns = st.columns(3, gap="small")
    for column, platform in zip(columns, PLATFORMS):
        with column:
            if st.button(platform, key=f"platform_{platform.lower()}", type="primary" if st.session_state.platform == platform else "secondary", width="stretch"):
                st.session_state.platform = platform
                clear_result()
                st.rerun()
    content_type = "Reel"
    if st.session_state.platform in ("Instagram", "TikTok"):
        content_type = st.radio("Content type", ["Reel", "Post", "Carousel"], horizontal=True, key="content_type", on_change=clear_result)
    gallery_mode = content_type != "Reel"
    st.html('<div class="field-label spaced"><b>02</b> Make it yours</div>')
    if gallery_mode:
        st.caption("Original images and videos · Individual downloads + ZIP for multiple items")
    else:
        st.radio("Choose a file format", ["MP4", "MP3"], key="kind", horizontal=True,
                 format_func=lambda x: "MP4 · Video" if x == "MP4" else "MP3 · Audio", label_visibility="collapsed", on_change=clear_result)
    st.html('<div class="field-label spaced"><b>03</b> Drop the link</div>')
    # A form makes Enter in the link field submit, so pasting a URL starts the
    # fetch without a second click. clear_on_submit keeps the link on screen.
    with st.form("get_video_form", border=False, clear_on_submit=False):
        url = st.text_input("Video URL", key="url", placeholder=f"Paste your {st.session_state.platform} {'post' if gallery_mode else 'video'} link here…", label_visibility="collapsed")
        submitted = st.form_submit_button("GetVideo  →", type="primary", width="stretch", key="get_video")
    if submitted:
        clear_result()
        animation = st.empty()
        try:
            checked_url = validate_url(url, st.session_state.platform)
            animation.html('<div class="processing"><div class="wave"><i></i><i></i><i></i><i></i><i></i></div><strong>Finding the good stuff…</strong><span>Checking your video and available qualities</span></div>')
            if gallery_mode:
                animation.empty()
                with st.spinner("Preparing your post…", show_time=True):
                    progress = st.progress(0, text="Finding the items in your post…")
                    try:
                        st.session_state.gallery_files = download_post(checked_url, st.session_state.platform, lambda value, message: progress.progress(value, text=message))
                    finally:
                        progress.empty()
            else:
                info = inspect_video(checked_url)
                st.session_state.media = {"info": info, "url": checked_url}
        except (MediaError, ValueError) as error:
            st.session_state.error = str(error)
            st.session_state.error_details = getattr(error, "details", None)
        except Exception as error:
            st.session_state.error = "Something interrupted processing. Please try again."
            st.session_state.error_details = str(error)
        finally:
            animation.empty()
    st.html('<div class="under-button">Your favorites. Simple downloads. <span>Just the way you like it.</span></div>')
    if st.session_state.error:
        st.error(st.session_state.error)
        if st.session_state.get("error_details"):
            with st.expander("Download error details"):
                st.code(st.session_state.error_details, language="text")

if st.session_state.get("gallery_files"):
    render_gallery(st.session_state.gallery_files)

if st.session_state.media:
    media = st.session_state.media
    info = media["info"]
    with st.container(border=True, key="result"):
        st.html('<div class="eyebrow result-eyebrow">✓ FOUND YOUR FAVORITE</div>')
        left, right = st.columns([1, 1.6])
        with left:
            thumbnail = info.get("thumbnail")
            if thumbnail and thumbnail.startswith("https://"):
                st.image(thumbnail, width="stretch")
        with right:
            st.subheader(info.get("title") or "Your video")
            duration = int(info.get("duration") or 0)
            st.caption(f"{info.get('uploader') or st.session_state.platform}  ·  {duration // 60}:{duration % 60:02d}")
            choices = video_qualities(info) if st.session_state.kind == "MP4" else [320, 192, 128]
            if choices:
                suffix = "p" if st.session_state.kind == "MP4" else " kbps"
                quality = st.selectbox("Download quality", choices, format_func=lambda q: f"{q}{suffix}", key="quality")
                if st.session_state.kind == "MP3":
                    st.caption("Conversion bitrate; sound quality depends on the original audio.")
                signature = (media["url"], st.session_state.kind, quality)
                st.session_state.setdefault("download_name", download_filename(info.get("title") or "GetVideo", st.session_state.kind))
                with st.form("rename_download", border=False):
                    filename_input = st.text_input("File name", value=st.session_state.download_name.rsplit(".", 1)[0],
                                                   key="filename_input", max_chars=120,
                                                   help="Choose a name, then press Enter or Apply name. The MP4/MP3 extension is added automatically.")
                    if st.form_submit_button("Apply name"):
                        st.session_state.download_name = download_filename(filename_input, st.session_state.kind)
                st.caption(f"Save as: {st.session_state.download_name}")
                if not st.session_state.prepared or st.session_state.prepared["signature"] != signature:
                    st.caption("Exact file size will appear once the file is prepared.")
                if st.button(f"Prepare {st.session_state.kind}  ↓", type="primary", width="stretch"):
                    st.session_state.prepared = None
                    progress = st.progress(0, text="Starting your download…")
                    try:
                        def update(value, status):
                            message = "Trying another download source…" if status == "retrying" else "Finishing your file…" if status == "finished" else "Downloading your favorite…"
                            progress.progress(value, text=message)
                        with st.spinner("Preparing your file. Almost yours…", show_time=True):
                            with tempfile.TemporaryDirectory(prefix="getvideo-") as directory:
                                path = download_media(media["url"], st.session_state.kind, quality, directory, update)
                                st.session_state.prepared = {"signature": signature, "name": path.name, "data": path.read_bytes()}
                        progress.progress(1.0, text="Ready. Take it with you.")
                    except MediaError as error:
                        progress.empty()
                        st.error(str(error))
                        if error.details:
                            with st.expander("Download error details"):
                                st.code(error.details, language="text")
                    except Exception as error:
                        progress.empty()
                        st.error("We couldn't prepare this file. Please try another video or quality.")
                        with st.expander("Download error details"):
                            st.code(str(error), language="text")
                ready = st.session_state.prepared
                if ready and ready["signature"] == signature:
                    file_size = format_size(len(ready["data"]))
                    st.caption(f"File size: {file_size}")
                    st.download_button(f"Download {st.session_state.kind} · {file_size}  ↓", data=ready["data"], file_name=st.session_state.download_name, mime="video/mp4" if st.session_state.kind == "MP4" else "audio/mpeg", type="primary", width="stretch")
            else:
                st.info("This video has no supported MP4 quality available. Try MP3 or another video.")
        ready = st.session_state.prepared
        if ready and choices and ready["signature"] == (media["url"], st.session_state.kind, quality):
            if st.session_state.kind == "MP4":
                st.video(ready["data"])
            else:
                st.audio(ready["data"], format="audio/mpeg")

st.html('''<section class="benefits"><div><span class="benefit-icon">↗</span><h3>From link to library.</h3><p>A few clicks. Your favorite content,<br>ready to go wherever you do.</p></div><div><span class="benefit-icon">◉</span><h3>Your format. Your call.</h3><p>Keep the whole video or just<br>the audio. You choose.</p></div><div><span class="benefit-icon">⌁</span><h3>Quality that fits.</h3><p>Choose from the resolutions<br>your video actually supports.</p></div></section>
<footer><span class="footer-brand">Get<span class="red">Video</span><small>Keep what moves you.</small></span><span>Download content you own or have permission to save.<br>Public content only · Up to 250 MB per download</span></footer>''')
