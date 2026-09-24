import streamlit as st

from download_details import download_filename, format_size
from gallery_downloads import gallery_zip


def render_gallery(files):
    with st.container(border=True, key="result"):
        st.subheader(f"Your post is ready · {len(files)} {'item' if len(files) == 1 else 'items'}")
        st.caption(f"Total media size: {format_size(sum(len(item['data']) for item in files))}")
        st.session_state.setdefault("gallery_name", "GetVideo-post")
        with st.form("rename_gallery", border=False):
            name = st.text_input("File name", value=st.session_state.gallery_name, max_chars=100)
            if st.form_submit_button("Apply name"):
                st.session_state.gallery_name = download_filename(name, "zip").removesuffix(".zip")
                st.session_state.pop("gallery_zip", None)
        name = st.session_state.gallery_name
        st.caption(f"Save as: {name}")
        if len(files) > 1:
            if "gallery_zip" not in st.session_state:
                st.session_state.gallery_zip = gallery_zip(files, name)
            bundle = st.session_state.gallery_zip
            st.download_button(f"Download all · ZIP · {format_size(len(bundle))}", bundle, f"{name}.zip", "application/zip", type="primary", width="stretch")
        for index, item in enumerate(files, 1):
            with st.expander(f"Item {index} · {item['extension'].upper()} · {format_size(len(item['data']))}", expanded=len(files) == 1):
                if item["mime"].startswith("video/"):
                    st.video(item["data"])
                else:
                    st.image(item["data"], width="stretch")
                filename = f"{name}{f'-{index:02d}' if len(files) > 1 else ''}.{item['extension']}"
                st.download_button(f"Download item {index}", item["data"], filename, item["mime"], key=f"gallery_download_{index}", width="stretch")
